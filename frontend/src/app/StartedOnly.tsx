import { Clock } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { useExperiment } from '@/api/queries'
import { PageTitle } from '@/components/common'
import { Card, EmptyState, ErrorState, Skeleton } from '@/components/ui/primitives'

/** Screens that need simulation output (forum, report, agent) explain a draft instead of failing. */
export function StartedOnly({ children }: { children: ReactNode }) {
  const { id = '' } = useParams()
  const experiment = useExperiment(id)

  if (experiment.error) return <ErrorState error={experiment.error} />
  if (!experiment.data) return <Skeleton className="h-96" />
  if (experiment.data.status !== 'draft') return children

  return (
    <>
      <PageTitle title={experiment.data.name} subtitle="Taslak deney" />
      <Card>
        <EmptyState icon={<Clock />} title="Bu deney henüz başlatılmadı.">
          Forum, rapor ve ajan ayrıntıları deney çalıştıktan sonra oluşur.{' '}
          <Link to="/experiments" className="text-primary underline-offset-4 hover:underline">
            Deneylere dön
          </Link>
        </EmptyState>
      </Card>
    </>
  )
}
