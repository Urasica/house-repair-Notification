import { useQuery } from '@tanstack/react-query'
import { catalogIsReady } from './api/catalog'

export default function App() {
  const catalog = useQuery({ queryKey: ['catalog-ready'], queryFn: catalogIsReady })

  return (
    <main className="shell">
      <header className="brand"><span className="brand-mark" aria-hidden="true">⌂</span> 우리집 보수 길잡이</header>
      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">우리 집의 불편함, 차근차근 확인해요</p>
        <h1 id="page-title">보수 안내를<br />쉽고 편안하게.</h1>
        <p className="description">주택과 증상을 선택하고 간단한 질문에 답하면,<br className="desktop-break" /> 관련 기준과 문의할 내용을 안내해 드려요.</p>
        <ol className="steps"><li>주택·증상 선택</li><li>간단 설문</li><li>안내 결과 확인</li></ol>
      </section>
      <section className="notice" aria-live="polite" aria-labelledby="notice-title">
        <h2 id="notice-title">{catalog.isError ? '잠시 연결이 어려워요' : '안내 서비스를 준비하고 있어요'}</h2>
        <p>{catalog.isError ? catalog.error.message : '정확한 안내를 위해 증상 목록과 관련 자료를 준비하고 있어요. 준비가 끝나면 설문을 시작할 수 있어요.'}</p>
        {catalog.isError
          ? <button onClick={() => void catalog.refetch()}>다시 확인하기</button>
          : <button disabled>설문 준비 중</button>}
      </section>
      <footer>실제 보수 여부는 담당 기관 확인이 필요해요.</footer>
    </main>
  )
}
