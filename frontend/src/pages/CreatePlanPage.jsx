import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import AppHeader from '../components/AppHeader'
import styles from './CreatePlanPage.module.css'

export default function CreatePlanPage() {
  const navigate = useNavigate()
  const { user, loading } = useAuth()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (!loading && !user) navigate('/login', { state: { fromUpload: true } })
  }, [user, loading, navigate])

  const handleSubmit = (e) => {
    e.preventDefault()
    console.log('Create plan (backend later):', { name, description })
  }

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />

      <main className={styles.main}>
        <div className={styles.card}>
          <h1 className={styles.title}>Create study plan</h1>
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
            <button type="submit" className={styles.btn}>Create plan</button>
          </form>
        </div>
      </main>
    </div>
  )
}
