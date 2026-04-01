import { useEffect, useRef, useState } from 'react'
import { plansApi } from '../api/client'
import styles from './PreplanChatPanel.module.css'

export default function PreplanChatPanel({ isOpen, onClose, documentIds, onApplyGoals }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [suggestedGoals, setSuggestedGoals] = useState('')
  const bodyRef = useRef(null)

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [messages])

  const handleClose = () => {
    setMessages([])
    setInput('')
    setSuggestedGoals('')
    onClose()
  }

  if (!isOpen) return null

  const sendMessage = async (text) => {
    const trimmed = (text || '').trim()
    if (!trimmed || loading) return

    const userMsg = { role: 'user', content: trimmed }
    const updated = [...messages, userMsg]
    setMessages(updated)
    setInput('')
    setLoading(true)

    try {
      const res = await plansApi.sendPreplanChat({
        documentIds,
        message: trimmed,
        history: updated.map((m) => ({ role: m.role, content: m.content })),
      })
      if (res.suggested_goals) setSuggestedGoals(res.suggested_goals)
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply || '' }])
    } catch (e) {
      const msg =
        e?.body?.detail ||
        'AI is not available right now. Please configure LLM_API_KEY on the backend and try again.'
      setMessages((prev) => [...prev, { role: 'assistant', content: msg }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className={styles.backdrop} onClick={handleClose} aria-hidden="true" />
      <aside className={styles.panel} role="dialog" aria-label="Pre-plan AI chat">
        <header className={styles.header}>
          <h2 className={styles.title}>AI: refine goals</h2>
          <button type="button" className={styles.closeBtn} onClick={handleClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className={styles.meta}>
          <div className={styles.metaRow}>
            <img src="/assets/ai_robot.png" alt="AI" className={styles.metaIcon} />
            <div className={styles.metaText}>
              Selected documents: <strong>{documentIds?.length || 0}</strong>
            </div>
          </div>
          <div className={styles.quickRow}>
            <button
              type="button"
              className={styles.quickBtn}
              onClick={() =>
                sendMessage(
                  'List the main topics you found in the selected materials. Ask me 3-5 clarifying questions, then propose a suggested goals text for the plan.'
                )
              }
              disabled={loading}
            >
              Analyze materials
            </button>
            {suggestedGoals && (
              <button
                type="button"
                className={styles.applyBtn}
                onClick={() => onApplyGoals(suggestedGoals)}
              >
                Use suggested goals
              </button>
            )}
          </div>
        </div>

        <div className={styles.body} ref={bodyRef}>
          {messages.length === 0 && (
            <div className={styles.welcome}>
              <p className={styles.welcomeText}>
                I can read the selected documents and help you write better learning goals for a higher-quality plan.
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={msg.role === 'user' ? styles.msgUser : styles.msgAssistant}>
              <div className={styles.msgContent}>{msg.content}</div>
            </div>
          ))}
          {loading && (
            <div className={styles.msgAssistant}>
              <div className={styles.msgContent}>
                <span className={styles.typing}>Thinking…</span>
              </div>
            </div>
          )}
        </div>

        <div className={styles.inputWrap}>
          <input
            type="text"
            className={styles.input}
            placeholder="Ask AI about topics/goals..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage(input)}
            disabled={loading}
          />
          <button
            type="button"
            className={styles.sendBtn}
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
          >
            ↑
          </button>
        </div>
      </aside>
    </>
  )
}

