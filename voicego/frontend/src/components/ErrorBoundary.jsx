import React from 'react';

// Catches render/effect errors so a single component bug never blanks the whole
// app (previously: a thrown error unmounted everything -> black screen).
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('App error:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: 24, color: '#fff', background: '#0d1117', minHeight: '100dvh',
          display: 'flex', flexDirection: 'column', gap: 12, justifyContent: 'center',
        }}>
          <h2 style={{ color: '#ef5350', margin: 0 }}>Đã xảy ra lỗi giao diện</h2>
          <p style={{ color: '#b6f5c8', fontFamily: 'monospace', fontSize: 14, wordBreak: 'break-word' }}>
            {String(this.state.error?.message || this.state.error)}
          </p>
          <button
            onClick={() => { this.setState({ error: null }); location.reload(); }}
            style={{ alignSelf: 'flex-start', padding: '12px 20px', borderRadius: 12, border: 'none',
                     background: '#00b14f', color: '#fff', fontWeight: 700, fontSize: 16 }}
          >
            Tải lại
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
