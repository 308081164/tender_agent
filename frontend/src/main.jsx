import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import MainLayoutRoute from './layouts/MainLayoutRoute'
import AdminLayout from './layouts/AdminLayout'
import HomePage from './pages/HomePage'
import WizardPage from './pages/WizardPage'
import SettingsPage from './pages/SettingsPage'
import NewProjectPage from './pages/NewProjectPage'
import PreviewPage from './pages/PreviewPage'
import CompanyPage from './pages/admin/CompanyPage'
import FieldsListPage from './pages/admin/FieldsListPage'
import FieldDetailPage from './pages/admin/FieldDetailPage'
import TemplatesListPage from './pages/admin/TemplatesListPage'
import TemplateDetailPage from './pages/admin/TemplateDetailPage'
import TemplatePreviewPage from './pages/admin/TemplatePreviewPage'
import QualificationsListPage from './pages/admin/QualificationsListPage'
import QualificationDetailPage from './pages/admin/QualificationDetailPage'
import ChecklistListPage from './pages/admin/ChecklistListPage'
import ChecklistDetailPage from './pages/admin/ChecklistDetailPage'
import FaqsListPage from './pages/admin/FaqsListPage'
import FaqDetailPage from './pages/admin/FaqDetailPage'
import ImportPage from './pages/admin/ImportPage'
import './styles/app.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route element={<MainLayoutRoute />}>
            <Route index element={<HomePage />} />
            <Route path="projects/new" element={<NewProjectPage />} />
            <Route path="projects/:id/step/:step" element={<WizardPage />} />
            <Route path="projects/:id/preview" element={<PreviewPage />} />
            <Route path="projects/:id" element={<Navigate to="step/1" replace />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="company" replace />} />
            <Route path="company" element={<CompanyPage />} />
            <Route path="fields" element={<FieldsListPage />} />
            <Route path="fields/:id" element={<FieldDetailPage />} />
            <Route path="templates" element={<TemplatesListPage />} />
            <Route path="templates/:id/preview" element={<TemplatePreviewPage />} />
            <Route path="templates/:id" element={<TemplateDetailPage />} />
            <Route path="qualifications" element={<QualificationsListPage />} />
            <Route path="qualifications/:id" element={<QualificationDetailPage />} />
            <Route path="checklist" element={<ChecklistListPage />} />
            <Route path="checklist/:id" element={<ChecklistDetailPage />} />
            <Route path="faqs" element={<FaqsListPage />} />
            <Route path="faqs/:id" element={<FaqDetailPage />} />
            <Route path="import" element={<ImportPage />} />
          </Route>
          <Route path="admin/data" element={<Navigate to="/admin/company" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)
