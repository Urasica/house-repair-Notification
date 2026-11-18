import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useStartSurvey } from '../features/survey/useStartSurvey'
import { Feedback, Waiting } from '../components/Feedback'

export default function Home() {
  const { auth, reference, query, catalog, busy, error, start } = useStartSurvey()
  const ongoing = reference && query.data && !query.isError ? query.data : null
  const preparing = catalog.error instanceof ApiError && catalog.error.code === 'CATALOG_NOT_READY'
  return <>
    <section className="intro" aria-labelledby="page-title">
      <h1 id="page-title">집 안의 불편함, 함께 살펴봐요</h1>
      <p className="description">불편한 곳을 알려 주세요. 관련 기준과 문의할 내용을 함께 살펴볼게요.</p>
      <ol className="steps"><li>증상 선택</li><li>질문 답변</li><li>결과 확인</li></ol>
    </section>
    <div className="entry-grid">
    <section className="notice start-panel" aria-live="polite" aria-labelledby="notice-title">
      {catalog.isPending ? <Waiting /> : preparing ? <><h2 id="notice-title">안내 서비스를 준비하고 있어요</h2><p>더 정확한 안내를 위해 자료를 준비하고 있어요. 준비가 끝나면 설문을 이용하실 수 있어요.</p><button disabled>설문 준비 중</button></> : catalog.isError ? <Feedback error={catalog.error} retry={() => void catalog.refetch()} /> : <>
        <h2 id="notice-title">몇 가지 질문으로 알아봐요</h2><p>{auth.data?.user ? '안내 결과는 ‘이전 결과’에 모아 둘게요. 나중에 다시 살펴보실 수 있어요.' : '로그인 없이도 괜찮아요. 몇 가지 질문에 편하게 답해 주세요.'}</p>
        <div className="actions home-survey-actions">
          {ongoing && <Link className="button-link" to={ongoing.currentResultId ? '/result/' + ongoing.currentResultId : '/survey'}>진행 중인 상담 이어가기</Link>}
          <button className={ongoing ? 'secondary' : undefined} disabled={busy || auth.isPending || auth.isError} onClick={() => void start()}>{busy ? '상담을 시작하고 있어요' : '새 설문 시작'}</button>
        </div>
      </>}
      {ongoing && !catalog.data && <p className="continue-link"><Link className="button-link" to={ongoing.currentResultId ? '/result/' + ongoing.currentResultId : '/survey'}>진행 중인 상담 이어가기</Link></p>}
      {auth.isError && <Feedback error={auth.error} retry={() => void auth.refetch()} />}
      {!!error && <Feedback error={error} />}
    </section>
    <section className="notice chat-entry" aria-labelledby="chat-entry-title">
      <p className="eyebrow">로그인 후 이용</p>
      <h2 id="chat-entry-title">챗봇에 편하게 물어보세요</h2>
      <p>궁금한 내용을 적어 주시면, 관련 자료를 살펴 안내해 드릴게요.</p>
      <Link className="button-link secondary" to="/chat">챗봇으로 질문하기</Link>
    </section>
    </div>
    <section className="notice privacy-panel" aria-labelledby="privacy-title">
      <h2 id="privacy-title">이용 전에 잠깐 살펴봐 주세요</h2>
      <p>이름이나 주소, 연락처는 적지 말아 주세요. 불편한 내용만 알려 주셔도 괜찮아요.</p>
      <details><summary>입력한 기록은 어떻게 쓰이나요?</summary>
      <ul>
        <li><strong>이용 시간:</strong> 상담과 로그인은 24시간 동안 유지돼요.</li>
        <li><strong>다시 보기:</strong> 비회원 설문은 현재 창의 상담 이용 시간 안에만 이어볼 수 있고, 로그인해도 계정으로 옮겨지지 않아요. 챗봇도 로그아웃하거나 창을 닫으면 새 대화로 시작해요.</li>
        <li><strong>상담 기록:</strong> 상담·대화 원문과 비회원 결과는 상담 이용 시간이 끝난 뒤 7일 안에 삭제해요.</li>
        <li><strong>회원 결과:</strong> 입력 내용, 답변, 출처와 함께 기본 5년 보관해요. ‘이전 결과’에서 삭제할 수 있어요.</li>
        <li><strong>서비스 개선:</strong> 개인을 알아볼 수 있는 내용을 뺀 질문의 종류와 선택 정보는 기본 5년 보관해요. 회원은 ‘이전 결과’에서, 비회원은 상담을 끝내기 전에 질문 기록 삭제를 선택할 수 있어요.</li>
        <li><strong>답변에 쓰는 자료:</strong> OpenAI에 선택한 항목·불러온 설문 답변의 이름, 법령 조문 번호, 검토한 자료를 보낼 수 있어요. 직접 입력한 질문 원문은 보내지 않아요.</li>
      </ul>
      <p>OpenAI에는 답변을 저장하지 않도록 요청해요. 다만 OpenAI의 자료 보관 규칙은 따로 적용돼요.</p>
      </details>
    </section>
  </>
}
