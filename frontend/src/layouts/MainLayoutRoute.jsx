import { Outlet } from 'react-router-dom'
import { useApp } from '../App'
import Layout from '../components/Layout'

export default function MainLayoutRoute() {
  const { settingsInfo, bootLoading, startNew } = useApp()

  return (
    <Layout
      settingsInfo={settingsInfo}
      loading={bootLoading}
      onStartNew={startNew}
    >
      <Outlet />
    </Layout>
  )
}
