import { useState, useRef, useEffect } from 'react'
import { plansApi } from '../api/client'
import styles from './AIChatPanel.module.css'

export default function AIChatPanel({ unitId, questionContext, onClearQuestion }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bodyRef = useRef(null)

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    if (questionContext) {
      const contextMsg = `Help me with this question: "${questionContext.text}"`
      handleSend(contextMsg)
    }
  }, [questionContext?.id])

  const handleSend = async (overrideMsg) => {
    const text = (overrideMsg || input).trim()
    if (!text || loading) return

    const userMsg = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])
    if (!overrideMsg) setInput('')
    setLoading(true)

    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }))
      const res = await plansApi.sendAiChat({
        unitId,
        questionId: questionContext?.id || null,
        message: text,
        history,
      })
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply }])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleClearChat = () => {
    setMessages([])
    if (onClearQuestion) onClearQuestion()
  }

  return (
    <aside className={styles.panel}>
      <header className={styles.header}>
        <h2 className={styles.title}>
          AI Tutor
          {questionContext && (
            <span className={styles.contextBadge}>Q: {questionContext.text.slice(0, 30)}…</span>
          )}
        </h2>
        {messages.length > 0 && (
          <button type="button" className={styles.clearBtn} onClick={handleClearChat}>
            Clear
          </button>
        )}
      </header>

      <div className={styles.body} ref={bodyRef}>
        {messages.length === 0 && (
          <div className={styles.empty}>
            <img src="/assets/ai_robot.png" alt="AI" className={styles.emptyIcon} />
            <p className={styles.emptyText}>
              Ask me anything about this unit! Click the AI icon next to any question for targeted help.
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={msg.role === 'user' ? styles.msgUser : styles.msgAssistant}
          >
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
          placeholder="Ask AI tutor..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={loading}
        />
        <button
          type="button"
          className={styles.sendBtn}
          onClick={() => handleSend()}
          disabled={loading || !input.trim()}
        >
          ↑
        </button>
      </div>
    </aside>
  )
}
