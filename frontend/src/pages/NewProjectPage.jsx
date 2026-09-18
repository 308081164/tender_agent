import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'

/** 兼容旧链接：重定向到首页并由全局确认弹窗创建标书。 */
export default function NewProjectPage() {
  const navigate = useNavigate()
  const { startNew } = useApp()

  useEffect(() => {
    navigate('/', { replace: true })
    startNew?.()
  }, [navigate, startNew])

  return null
}
