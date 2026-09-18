import React from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { ADMIN_MODULES } from '../constants/admin'

export default function AdminLayout() {
  const navigate = useNavigate()

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <button type="button" className="ghost admin-back" onClick={() => navigate('/')}>
          ← 返回工作台
        </button>
        <h1 className="admin-brand">基础数据</h1>
        <p className="admin-brand-sub">维护企业档案、模板、资质与校验规则</p>
        <nav className="admin-nav">
          {ADMIN_MODULES.map((m) => (
            <NavLink
              key={m.path}
              to={`/admin/${m.path}`}
              className={({ isActive }) => `admin-nav-item${isActive ? ' active' : ''}`}
            >
              <span className="admin-nav-label">{m.label}</span>
              <span className="admin-nav-desc">{m.desc}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  )
}
