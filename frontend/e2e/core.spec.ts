import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

async function accessible(page: Page) {
  const report = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(report.violations).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

async function survey(page: Page) {
  await page.getByRole('button', { name: '새 설문 시작', exact: true }).click()
  await page.getByRole('radio').first().check()
  await page.getByLabel('공간', { exact: true }).selectOption({ index: 1 })
  await page.getByLabel('시설물', { exact: true }).selectOption({ index: 1 })
  await page.getByLabel('증상', { exact: true }).selectOption({ index: 1 })
  await page.getByRole('button', { name: '저장하고 설문으로' }).click()
  await expect(page.getByRole('heading', { name: '간단히 확인해 주세요' })).toBeVisible()
  // Real catalog: answer every currently active question UNKNOWN and allow new branches.
  for (let attempt = 0; attempt < 30; attempt++) {
    const unanswered = page.locator('fieldset').filter({ hasNot: page.locator('input:checked') })
    if (await unanswered.count() === 0) break
    const radio = unanswered.first().locator('input[value="UNKNOWN"]')
    await expect(radio).toBeEnabled()
    const saved = page.waitForResponse(r => r.url().endsWith('/context') && r.request().method() === 'PUT')
    await radio.check()
    expect((await saved).status()).toBe(200)
    await expect(page.getByRole('button', { name: '안내 결과 확인', exact: true })).toBeEnabled()
  }
  await accessible(page)
  await page.getByRole('button', { name: '안내 결과 확인', exact: true }).click()
  // The live search path can exceed the default 5s assertion; the API client allows 15s.
  await expect(page).toHaveURL(/\/result\//, { timeout: 15000 })
  await accessible(page)
}

test('guest real catalog survey, keyboard, deletion and member restriction', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('입력과 기록은 이렇게 사용해요')).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: /우리집 보수 길잡이/ })).toBeFocused()
  await accessible(page)
  await survey(page)
  await page.reload()
  await expect(page).toHaveURL(/\/result\//)
  await page.getByRole('button', { name: '상담 종료', exact: true }).click()
  await page.getByRole('checkbox', { name: '정제된 질문 기록도 삭제' }).check()
  await page.getByRole('button', { name: '종료 확인' }).click()
  await expect(page).toHaveURL('/')
  await page.getByRole('link', { name: '이전 결과', exact: true }).click()
  await expect(page.getByRole('heading', { name: /로그인/ })).toBeVisible()
})

test('member chat restores, result deletion, logout and cache protection', async ({ page }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: '회원가입', exact: true }).click()
  await page.getByLabel('이메일', { exact: true }).fill(`e2e-${Date.now()}@example.com`)
  await page.getByLabel('비밀번호', { exact: true }).fill('test-only-strong-passphrase')
  await page.getByRole('button', { name: '가입하기', exact: true }).click()
  await expect(page.getByRole('heading', { name: '로그인', exact: true })).toBeVisible()
  await page.getByLabel('비밀번호', { exact: true }).fill('test-only-strong-passphrase')
  await page.getByRole('button', { name: '로그인하기', exact: true }).click()
  await expect(page).toHaveURL('/')
  await survey(page)
  await page.getByRole('link', { name: '챗봇', exact: true }).click()
  await page.getByRole('textbox').fill('제16조 내용을 설명해 주세요')
  await page.getByRole('button', { name: '질문 보내기', exact: true }).click()
  await expect(page.getByText('대화가 저장됐어요.')).toBeVisible()
  await expect(page.getByRole('list', { name: '저장된 대화' }).locator(':scope > li')).toHaveCount(1)
  await page.reload()
  await expect(page.getByRole('list', { name: '저장된 대화' }).locator(':scope > li')).toHaveCount(1)
  await accessible(page)
  await page.getByRole('link', { name: '이전 결과', exact: true }).click()
  await page.locator('.history-list a').first().click()
  await page.getByRole('button', { name: '이 결과 삭제', exact: true }).click()
  await page.getByRole('button', { name: '삭제 확인', exact: true }).click()
  await expect(page.getByText('저장된 이전 결과가 없어요.')).toBeVisible()
  await page.getByRole('button', { name: '로그아웃', exact: true }).click()
  await page.goto('/chat')
  await expect(page.getByRole('heading', { name: /로그인/ })).toBeVisible()
  await expect(page.getByText('제16조 내용을 설명해 주세요')).toHaveCount(0)
})
