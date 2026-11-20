import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useStartSurvey } from '../features/survey/useStartSurvey'
import { Feedback, Waiting } from '../components/Feedback'

export default function Home() {
  const { auth, reference, query, catalog, busy, error, start } = useStartSurvey()
  const ongoing = reference && query.data && !query.isError ? query.data : null
  const preparing = catalog.error instanceof ApiError && catalog.error.code === 'CATALOG_NOT_READY'
  const continuePath = ongoing?.currentResultId ? `/result/${ongoing.currentResultId}` : '/survey'

  return <>
    <section className="home-intro" aria-labelledby="page-title">
      <div className="home-intro-copy">
        <p className="home-scope">임대주택 보수 안내</p>
        <h1 id="page-title">집 안의 불편함,<br />함께 살펴봐요</h1>
        <p className="home-description">불편한 곳을 알려 주세요.<br />관련 기준과 문의할 내용을 함께 살펴볼게요.</p>
      </div>
    </section>
    <section className="home-services" aria-labelledby="services-title">
      <h2 id="services-title">서비스 바로가기</h2>
      <div className="service-grid">
        <section className="home-service" aria-labelledby="survey-entry-title">
          <span className="service-icon survey-icon" aria-hidden="true" />
          <div className="service-content" aria-live="polite">
            <h3 id="survey-entry-title">간단 설문</h3>
            {catalog.isPending ? <Waiting /> : preparing ? <>
              <p>안내 서비스를 준비하고 있어요.<br />자료가 준비되면 설문을 이용하실 수 있어요.</p>
              <div className="service-actions"><button disabled>설문 준비 중</button></div>
            </> : catalog.isError ? <Feedback error={catalog.error} retry={() => void catalog.refetch()} /> : <>
              <p>{auth.data?.user
                ? <>증상을 고르고 질문에 답해 주세요.<br />안내는 ‘이전 결과’에서 다시 볼 수 있어요.</>
                : <>증상을 고르고 답해 주세요.<br />로그인 없이 이용할 수 있어요.</>}</p>
              <div className="service-actions">
                {ongoing && <Link className="button-link" to={continuePath}>진행 중인 상담 이어가기</Link>}
                <button className={ongoing ? 'secondary' : undefined} disabled={busy || auth.isPending || auth.isError} onClick={() => void start()}>{busy ? '상담을 시작하고 있어요' : '새 설문 시작'}</button>
              </div>
            </>}
            {ongoing && !catalog.data && <div className="service-actions"><Link className="button-link" to={continuePath}>진행 중인 상담 이어가기</Link></div>}
            {auth.isError && <Feedback error={auth.error} retry={() => void auth.refetch()} />}
            {!!error && <Feedback error={error} />}
          </div>
        </section>
        <section className="home-service" aria-labelledby="chat-entry-title">
          <span className="service-icon chat-icon" aria-hidden="true" />
          <div className="service-content">
            <h3 id="chat-entry-title">챗봇 상담</h3>
            <p>로그인한 뒤 질문해 주세요.<br />관련 자료를 찾아볼게요.</p>
            <div className="service-actions"><Link className="button-link secondary" to="/chat">챗봇으로 질문하기</Link></div>
          </div>
        </section>
      </div>
    </section>
    <section className="privacy-panel" aria-labelledby="privacy-title">
      <h2 id="privacy-title">이용 전에 잠깐 살펴봐 주세요</h2>
      <p>이름·주소·연락처는 적지 말아 주세요.<br />불편한 내용만 알려 주셔도 괜찮아요.</p>
      <details><summary>입력한 기록은 어떻게 쓰이나요?</summary>
        <ul>
          <li><strong>이용 시간</strong><br />상담과 로그인은 24시간 동안 유지돼요.</li>
          <li><strong>다시 보기</strong><br />비회원 설문은 상담이 끝나기 전까지 현재 창에서만 이어볼 수 있어요. 로그인해도 계정으로 옮겨지지 않아요.<br />챗봇은 로그아웃하거나 창을 닫으면 새 대화로 시작해요.</li>
          <li><strong>상담 기록</strong><br />상담·대화 원문과 비회원 결과는 상담 이용 시간이 끝난 뒤 7일 안에 삭제해요.</li>
          <li><strong>회원 결과</strong><br />입력 내용, 답변, 출처와 함께 기본 5년 보관해요.<br />‘이전 결과’에서 삭제할 수 있어요.</li>
          <li><strong>서비스 개선</strong><br />개인을 알아볼 수 있는 내용을 뺀 질문의 종류와 선택 정보는 기본 5년 보관해요.<br />회원은 ‘이전 결과’에서, 비회원은 상담을 끝내기 전에 질문 기록 삭제를 선택할 수 있어요.</li>
          <li><strong>답변에 쓰는 자료</strong><br />OpenAI에 선택 항목과 불러온 설문 답변의 이름, 법령 조문 번호, 검토한 자료를 보낼 수 있어요.<br />직접 입력한 질문 원문은 보내지 않아요.</li>
        </ul>
        <p>OpenAI에는 답변을 저장하지 않도록 요청해요.<br />OpenAI의 자료 보관 규칙은 따로 적용돼요.</p>
      </details>
    </section>
  </>
}
