import { Outlet } from 'react-router-dom'
import { useApp } from '../App'
import Layout from '../components/Layout'

export default function MainLayoutRoute() {
  const {
    showToast, settingsInfo, wizardLayout, bootLoading, startNew,
  } = useApp()

  return (
    <Layout
      project={wizardLayout.project}
      activeStep={wizardLayout.activeStep}
      onGoStep={wizardLayout.onGoStep}
      settingsInfo={settingsInfo}
      loading={wizardLayout.loading || bootLoading}
      onStartNew={startNew}
    >
      <Outlet />
    </Layout>
  )
}
