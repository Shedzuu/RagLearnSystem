import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { plansApi } from '../api/client'
import AppHeader from '../components/AppHeader'
import styles from './CreatePlanPage.module.css'

export default function CreatePlanPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, loading } = useAuth()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const uploadedFile = location.state?.uploadedFile || null

  useEffect(() => {
    if (!loading && !user) navigate('/login', { state: { fromUpload: true } })
  }, [user, loading, navigate])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const plan = await plansApi.createPlan({ title: name, description })
      if (uploadedFile) {
        try {
          await plansApi.uploadDocument(plan.id, uploadedFile)
        } catch (_) {
          // На дипломе достаточно, если план создался; ошибку загрузки файла можно залогировать
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
          <h1 className={styles.title}>Create study plan</h1>
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
            <button type="submit" className={styles.btn} disabled={submitting}>
              {submitting ? 'Creating…' : 'Create plan'}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}
