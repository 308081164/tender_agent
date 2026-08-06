import React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import AdminDetailHeader from '../../components/admin/AdminDetailHeader'
import TemplatePreviewPanel from '../../components/admin/TemplatePreviewPanel'

export default function TemplatePreviewPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  return (
    <>
      <AdminDetailHeader
        title="模板内容预览"
        backTo="/admin/templates"
        extra={(
          <>
            <Link className="ghost linkish" to={`/admin/templates/${id}`}>编辑元数据</Link>
            <a className="ghost linkish" href={api.adminTemplateDownloadUrl(id)} download>下载 DOCX</a>
          </>
        )}
      />
      <div className="card-block admin-template-preview-page">
        <TemplatePreviewPanel templateId={id} />
      </div>
      <div className="actions" style={{ marginTop: 16 }}>
        <button type="button" className="secondary" onClick={() => navigate('/admin/templates')}>返回列表</button>
        <button type="button" onClick={() => navigate(`/admin/templates/${id}`)}>编辑模板</button>
      </div>
    </>
  )
}
