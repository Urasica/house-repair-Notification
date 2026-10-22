import { expect, test, type Page, type TestInfo } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { readFileSync } from 'node:fs'
import { catalog, filledSession, member, questionsFixture, resultFixture, sessionFixture, testToken } from '../src/features/survey/test-fixtures'
import type { Catalog, Context } from '../src/features/survey/storage'
import type { ChatResponse } from '../src/features/chat/api'

async function mockUI(page: Page, signedIn = false, choices: Catalog = catalog) {
  let session = { ...sessionFixture(signedIn), catalogVersion: choices.version }
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api/v1', '')
    if (path === '/auth/me') return route.fulfill({ json: signedIn ? member : { user: null, csrfToken: null } })
    if (path === '/auth/register') return route.fulfill({ status: 201, json: member.user })
    if (path === '/auth/login') { signedIn = true; return route.fulfill({ json: member }) }
    if (path === '/catalog') return route.fulfill({ json: choices })
    if (path === '/sessions' && request.method() === 'POST') {
      session = { ...sessionFixture(signedIn), catalogVersion: choices.version, purpose: (request.postDataJSON() as { purpose: 'SURVEY' | 'CHAT' }).purpose }
      return route.fulfill({ json: { session, sessionToken: signedIn ? null : testToken } })
    }
    if (path.endsWith('/context')) {
      session = { ...session, context: (request.postDataJSON() as { context: Context }).context, revision: session.revision + 1 }
      return route.fulfill({ json: session })
    }
    if (path.endsWith('/questions')) return route.fulfill({ json: questionsFixture(session) })
    if (path.endsWith('/chat/survey-context')) {
      session = { ...session, context: filledSession(true).context, revision: session.revision + 1 }
      return route.fulfill({ json: session })
    }
    if (path.endsWith('/evaluations')) {
      session.currentResultId = resultFixture(session).id
      return route.fulfill({ json: resultFixture(session) })
    }
    if (path.endsWith('/chat/messages')) {
      const reply: ChatResponse = {
        requestId: session.id, contextRevision: session.revision, answerMode: 'CLARIFY', status: 'NEED_MORE_INFO', isCurrent: true,
        userMessage: { id: session.id, requestId: session.id, role: 'USER', content: '시험용 질문입니다.', citations: [], createdAt: session.createdAt, isCurrent: true },
        assistantMessage: { id: session.id, requestId: session.id, role: 'ASSISTANT', content: '시험용 답변입니다. 필요한 내용을 이 대화에서 확인해 주세요.', citations: [], createdAt: session.createdAt, isCurrent: true },
        followUpQuestions: ['어떤 부분이 불편한가요?'], disclaimer: '실제 보수 여부는 담당 기관 확인이 필요해요.',
      }
      return route.fulfill({ json: { items: [reply], nextCursor: null } })
    }
    if (path === '/me/results') return route.fulfill({ json: { items: [resultFixture(session)], nextCursor: null } })
    if (path.includes('/results/')) return route.fulfill({ json: resultFixture(session) })
    if (path === '/sessions/' + session.id) return route.fulfill({ json: session })
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message: '시험에 정의하지 않은 요청' } } })
  })
}

async function visibleControls(page: Page, name: string, info: TestInfo) {
  const report = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(report.violations).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  for (const control of await page.locator('.topbar nav a, button, .button-link, .choice, select, summary').all()) {
    if (!await control.isVisible()) continue
    const box = await control.boundingBox()
    expect(box?.height, await control.innerText()).toBeGreaterThanOrEqual(44)
    expect(box?.width, await control.innerText()).toBeGreaterThanOrEqual(44)
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  }
  await page.screenshot({ path: `../artifacts/ui-20261019-copy/${info.project.name}-${name}.png`, fullPage: name !== 'home', scale: 'css' })
}

async function compactHome(page: Page) {
  if (page.viewportSize()!.width > 600) return
  expect((await page.locator('.topbar').boundingBox())!.height).toBeLessThanOrEqual(112)
  await expect(page.getByRole('button', { name: '새 설문 시작', exact: true })).toBeInViewport({ ratio: 1 })
  await expect(page.getByRole('link', { name: '챗봇으로 질문하기' })).toBeInViewport({ ratio: 1 })
}

test('home navigation, login and narrow screens keep visible controls', async ({ page }, info) => {
  await mockUI(page)
  await page.goto('/')
  await expect(page.getByRole('button', { name: '새 설문 시작', exact: true })).toBeEnabled()
  await expect(page.getByRole('link', { name: '홈', exact: true })).toHaveAttribute('aria-current', 'page')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: /우리집 보수 길잡이/ })).toBeFocused()
  await page.keyboard.press('Tab')
  const home = page.getByRole('link', { name: '홈', exact: true })
  await expect(home).toBeFocused()
  expect(await home.evaluate(element => getComputedStyle(element).outlineWidth)).toBe('3px')
  await compactHome(page)
  await page.getByRole('heading', { level: 1 }).click()
  await visibleControls(page, 'home', info)
  await page.getByText('입력한 기록은 어떻게 쓰이나요?', { exact: true }).click()
  await expect(page.getByText(/상담과 로그인은 24시간 동안 유지돼요/)).toBeVisible()
  await expect(page.getByText(/직접 입력한 질문 원문은 보내지 않아요/)).toBeVisible()
  await visibleControls(page, 'privacy-open', info)
  await page.getByRole('link', { name: '챗봇으로 질문하기' }).click()
  await expect(page.getByRole('heading', { name: '로그인 후 이용해 주세요' })).toBeVisible()
  await page.getByRole('link', { name: '로그인하기', exact: true }).click()
  await expect(page.getByLabel('이메일', { exact: true })).toBeVisible()
  await visibleControls(page, 'login', info)
  for (const width of [320, 768]) {
    await page.setViewportSize({ width, height: 800 })
    await visibleControls(page, `login-${width}`, info)
    await page.getByRole('link', { name: '홈', exact: true }).click()
    await expect(page.getByRole('button', { name: '새 설문 시작', exact: true })).toBeEnabled()
    await compactHome(page)
    await visibleControls(page, `home-${width}`, info)
    await page.getByRole('link', { name: '로그인', exact: true }).click()
    await expect(page.getByLabel('이메일', { exact: true })).toBeVisible()
  }
})

test('selection, answers, result and end confirmation remain readable', async ({ page }, info) => {
  await mockUI(page)
  await page.goto('/')
  await page.getByRole('button', { name: '새 설문 시작', exact: true }).click()
  await page.getByRole('radio').first().check()
  await page.getByLabel('공간', { exact: true }).selectOption('test-room')
  await page.getByLabel('시설물', { exact: true }).selectOption('test-facility')
  await page.getByLabel('증상', { exact: true }).selectOption('test-symptom')
  await visibleControls(page, 'select', info)
  await page.getByRole('button', { name: '저장하고 설문으로' }).click()
  await expect(page.getByRole('heading', { name: '간단히 확인해 주세요' })).toBeFocused()
  await expect(page.getByRole('heading', { name: '간단히 확인해 주세요' })).toBeInViewport()
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  await page.getByRole('button', { name: '안내 결과 확인', exact: true }).click()
  await expect(page.getByText('답을 골라 주세요. 모르면 ‘모름’을 선택해도 괜찮아요.')).toBeVisible()
  await expect(page.getByRole('radio').first()).toBeFocused()
  await expect(page).toHaveURL('/survey')
  await page.getByRole('radio', { name: '모름', exact: true }).check()
  await expect(page.getByRole('radio', { name: '모름', exact: true })).toBeChecked()
  await expect(page.getByRole('button', { name: '안내 결과 확인', exact: true })).toBeEnabled()
  await visibleControls(page, 'survey', info)
  await page.getByRole('button', { name: '안내 결과 확인', exact: true }).click()
  await expect(page).toHaveURL(/\/result\//)
  await page.getByRole('button', { name: '상담 종료', exact: true }).click()
  await visibleControls(page, 'result-confirm', info)
})

for (const succeeds of [true, false]) test(`signup continues to login without password re-entry (success=${succeeds})`, async ({ page }) => {
  await mockUI(page)
  if (!succeeds) await page.route('**/api/v1/auth/login', route => route.fulfill({ status: 503, json: { error: { code: 'SERVICE_UNAVAILABLE', message: '연결을 확인해 주세요.' } } }))
  await page.goto('/')
  await page.getByRole('button', { name: '새 설문 시작', exact: true }).click()
  await expect(page).toHaveURL('/select')
  await page.getByRole('link', { name: '이전 결과', exact: true }).click()
  await page.getByRole('link', { name: '로그인하기', exact: true }).click()
  await expect(page.getByText(/로그인하면 진행 중인 비회원 상담은/)).toBeVisible()
  await page.getByRole('button', { name: '회원가입', exact: true }).click()
  await page.getByLabel('이메일', { exact: true }).fill('signup-only@example.com')
  await page.getByLabel('비밀번호', { exact: true }).fill('test-only-strong-passphrase')
  await page.getByRole('button', { name: '가입하기', exact: true }).click()
  if (succeeds) { await expect(page).toHaveURL('/history'); await expect(page.locator('.history-list a')).toBeVisible() }
  else {
    await expect(page.getByText(/가입은 완료됐어요/)).toBeVisible()
    await expect(page.getByRole('heading', { name: '로그인', exact: true })).toBeVisible()
    await expect(page.getByLabel('비밀번호', { exact: true })).toHaveValue('')
    await expect(page.getByLabel('이메일', { exact: true })).toHaveValue('signup-only@example.com')
  }
})

test('kitchen sink finishing links everyday leakage to the existing pipe symptom', async ({ page }) => {
  const reviewed = JSON.parse(readFileSync(new URL('../../data/catalog/m08a-20261004/catalog.json', import.meta.url), 'utf8')) as Catalog
  await mockUI(page, false, reviewed)
  await page.goto('/')
  await page.getByRole('button', { name: '새 설문 시작', exact: true }).click()
  await page.getByLabel('공간', { exact: true }).selectOption('kitchen')
  await page.getByLabel('시설물', { exact: true }).selectOption('sink')
  await page.getByRole('button', { name: '싱크대 아래에서 물이 새요' }).click()
  await expect(page.getByLabel('시설물', { exact: true })).toHaveValue('pipe')
  await expect(page.getByLabel('증상', { exact: true })).toHaveValue('leak')
})

test('member chat reset and history deletion keep distinct actions', async ({ page }, info) => {
  await mockUI(page, true)
  await page.goto('/')
  await expect(page.getByRole('button', { name: '새 설문 시작', exact: true })).toBeEnabled()
  await compactHome(page)
  await page.goto('/chat')
  await expect(page.getByText('시험용 답변입니다.', { exact: false })).toBeVisible()
  await page.getByLabel('궁금한 내용', { exact: true }).fill('시험용 질문')
  await expect(page.getByRole('button', { name: '질문 보내기', exact: true })).toBeEnabled()
  await visibleControls(page, 'chat', info)
  await page.getByRole('button', { name: '이전 설문 불러오기', exact: true }).click()
  await page.getByLabel('불러올 설문 결과', { exact: true }).selectOption({ index: 1 })
  await page.getByRole('button', { name: '선택한 설문 불러오기', exact: true }).click()
  await expect(page.getByText(/선택한 설문을 불러왔어요/)).toBeVisible()
  await expect(page.getByText(/확인한 내용:.*설문 답변 1개/)).toBeVisible()
  await page.getByRole('button', { name: '대화 초기화', exact: true }).click()
  await visibleControls(page, 'chat-confirm', info)
  await page.getByRole('button', { name: '취소', exact: true }).click()
  await expect(page.getByLabel('궁금한 내용', { exact: true })).toBeFocused()
  await page.getByRole('link', { name: '이전 결과', exact: true }).click()
  await expect(page.locator('.history-list a')).toBeVisible()
  await visibleControls(page, 'history', info)
  await page.getByRole('button', { name: '내 질문 기록 전체 삭제', exact: true }).click()
  await expect(page.getByRole('button', { name: '취소', exact: true })).toBeFocused()
  await visibleControls(page, 'history-confirm', info)
  await page.setViewportSize({ width: 320, height: 900 })
  await visibleControls(page, 'history-confirm-320', info)
  await page.getByRole('button', { name: '취소', exact: true }).click()
  await expect(page.getByRole('button', { name: '내 질문 기록 전체 삭제', exact: true })).toBeFocused()
  await page.locator('.history-list a').click()
  await page.getByRole('button', { name: '이 결과 삭제', exact: true }).click()
  await expect(page.getByRole('button', { name: '취소', exact: true })).toBeFocused()
  await page.getByRole('button', { name: '취소', exact: true }).click()
  await expect(page.getByRole('button', { name: '이 결과 삭제', exact: true })).toBeFocused()
})
