import { Outlet } from 'react-router-dom'
import { useApp } from '../App'
import Layout from '../components/Layout'

export default function MainLayoutRoute() {
  const { settingsInfo } = useApp()

  return (
    <Layout settingsInfo={settingsInfo}>
      <Outlet />
    </Layout>
  )
}
