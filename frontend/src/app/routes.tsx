import { lazy, Suspense, type ReactNode } from 'react'
import { isRouteErrorResponse, Link, Navigate, useRouteError, type RouteObject } from 'react-router'
import { RequireAuth } from '@/auth/guards'
import { Skeleton } from '@/components/ui/primitives'
import { LandingPage } from '@/pages/LandingPage'
import { LoginPage } from '@/pages/LoginPage'
import { ExperimentsPage } from '@/pages/ExperimentsPage'
import { ExperimentLayout } from './ExperimentLayout'
import { Layout } from './Layout'
import { StartedOnly } from './StartedOnly'

// Chart-heavy screens are code-split so the login screen stays small.
const NewExperimentPage = lazy(() => import('@/pages/NewExperimentPage'))
const LivePage = lazy(() => import('@/pages/LivePage'))
const AgentPage = lazy(() => import('@/pages/AgentPage'))
const ForumPage = lazy(() => import('@/pages/ForumPage'))
const ReportPage = lazy(() => import('@/pages/ReportPage'))
const AccountPage = lazy(() => import('@/pages/AccountPage'))

const page = (node: ReactNode) => (
  <Suspense fallback={<Skeleton className="h-96 w-full" />}>{node}</Suspense>
)

function RouteError() {
  const err = useRouteError()
  const notFound = isRouteErrorResponse(err) && err.status === 404
  return (
    <div className="mx-auto max-w-md p-10 text-center">
      <h1 className="text-xl font-semibold">
        {notFound ? 'Sayfa bulunamadı' : 'Bir şeyler ters gitti'}
      </h1>
      <Link to="/experiments" className="mt-4 inline-block text-sm text-primary underline">
        Deneylere dön
      </Link>
    </div>
  )
}

export const routes: RouteObject[] = [
  { path: '/', element: <LandingPage /> },
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    errorElement: <RouteError />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: 'experiments', element: <ExperimentsPage /> },
          { path: 'account', element: page(<AccountPage />) },
          {
            element: <RequireAuth requiredRole="researcher" />,
            children: [{ path: 'experiments/new', element: page(<NewExperimentPage />) }],
          },
          {
            path: 'experiments/:id',
            element: <ExperimentLayout />,
            children: [
              { index: true, element: <Navigate to="live" replace /> },
              { path: 'live', element: page(<LivePage />) },
              {
                path: 'agents/:agentId',
                element: page(
                  <StartedOnly>
                    <AgentPage />
                  </StartedOnly>,
                ),
              },
              {
                path: 'forum',
                element: page(
                  <StartedOnly>
                    <ForumPage />
                  </StartedOnly>,
                ),
              },
              {
                path: 'report',
                element: page(
                  <StartedOnly>
                    <ReportPage />
                  </StartedOnly>,
                ),
              },
            ],
          },
          { path: '*', element: <RouteError /> },
        ],
      },
    ],
  },
]
