import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSurvey } from '../features/survey/useSurvey'
import { getCatalog } from '../features/survey/api'
import type { Catalog, Session, SessionRef } from '../features/survey/storage'
import { Feedback, NeedSession, Waiting } from './Feedback'

export default function Consultation({ children }: { children: (session: Session, ref: SessionRef, catalog: Catalog) => ReactNode }) {
  const { auth, reference, query } = useSurvey()
  const catalog = useQuery({ queryKey: ['catalog', query.data?.catalogVersion], enabled: !!query.data,
    queryFn: ({ signal }) => getCatalog(query.data!.catalogVersion, signal), retry: false, refetchOnWindowFocus: false })
  if (auth.isPending) return <Waiting />
  if (auth.isError) return <Feedback error={auth.error} retry={() => void auth.refetch()} />
  if (!reference) return <NeedSession />
  if (query.isError) return <Feedback error={query.error} retry={() => void query.refetch()} />
  if (query.isPending || catalog.isPending) return <Waiting />
  if (catalog.isError) return <Feedback error={catalog.error} retry={() => void catalog.refetch()} />
  return children(query.data, reference, catalog.data)
}
