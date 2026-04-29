import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { plansApi } from '../api/client'
import AppHeader from '../components/AppHeader'
import PreplanChatPanel from '../components/PreplanChatPanel'
import styles from './CreatePlanPage.module.css'

export default function CreatePlanPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, loading } = useAuth()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [goals, setGoals] = useState('')
  const [preplanChatOpen, setPreplanChatOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const uploadedFile = location.state?.uploadedFile || null
  const selectedDocumentIds = location.state?.selectedDocumentIds || []

  useEffect(() => {
    if (!loading && !user) navigate('/login', { state: { fromUpload: true } })
  }, [user, loading, navigate])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const plan = await plansApi.createPlan({ title: name, description, goals })
      if (selectedDocumentIds.length) {
        try {
          await plansApi.attachDocuments(plan.id, selectedDocumentIds)
        } catch (_) {
          // Не критично для успешного создания плана
        }
      }
      navigate('/plans')
    } catch (err) {
      setError(err.body?.detail || err.message || 'Failed to create plan')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />

      <main className={styles.main}>
        <div className={styles.card}>
          <div className={styles.hero}>
            <div>
              <p className={styles.eyebrow}>Plan setup</p>
              <h1 className={styles.title}>Create study plan</h1>
              <p className={styles.subtitle}>
                Name the plan, describe the learning outcome, and let AI help shape the goals.
              </p>
            </div>
            <div className={styles.infoPanel}>
              <p className={styles.infoLabel}>Selected materials</p>
              <strong className={styles.infoValue}>{selectedDocumentIds.length}</strong>
              <p className={styles.infoHint}>
                {selectedDocumentIds.length > 0
                  ? 'Your selected documents will be attached right after the plan is created.'
                  : 'You can still create the plan first and attach materials later.'}
              </p>
            </div>
          </div>
          {error && <p className={styles.error}>{error}</p>}
          <form onSubmit={handleSubmit} className={styles.form}>
            <label className={styles.label}>
              Name *
              <input
                type="text"
                className={styles.input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
            <label className={styles.label}>
              Description (optional)
              <textarea
                className={styles.textarea}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
              />
            </label>
            <label className={styles.label}>
              Learning goals (optional)
              <textarea
                className={styles.textarea}
                value={goals}
                onChange={(e) => setGoals(e.target.value)}
                rows={3}
                placeholder="E.g. learn loops, variables, conditionals and dictionaries from the selected materials."
              />
            </label>
            <button
              type="button"
              className={styles.aiBtn}
              onClick={() => setPreplanChatOpen(true)}
            >
              Help me write goals with AI
            </button>
            <button type="submit" className={styles.btn} disabled={submitting}>
              {submitting ? 'Creating…' : 'Create plan'}
            </button>
          </form>
        </div>
      </main>

      <PreplanChatPanel
        isOpen={preplanChatOpen}
        onClose={() => setPreplanChatOpen(false)}
        documentIds={selectedDocumentIds}
        planTitle={name}
        planDescription={description}
        goalsDraft={goals}
        onApplyGoals={(text) => {
          setGoals(text)
          setPreplanChatOpen(false)
        }}
      />
    </div>
  )
}
