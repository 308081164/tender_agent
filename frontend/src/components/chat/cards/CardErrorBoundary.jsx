import React from 'react'

/** 卡片渲染错误边界：单个卡片异常时内联提示，避免整个对话页崩溃。 */
export default class CardErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="chat-card">
          <div className="chat-card-body">
            <span className="chat-card-hint">
              卡片渲染失败：{String(this.state.error?.message || this.state.error)}
            </span>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
