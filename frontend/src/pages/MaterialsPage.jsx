import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AppHeader from '../components/AppHeader'
import { useAuth } from '../context/AuthContext'
import { documentsApi } from '../api/client'
import styles from './MaterialsPage.module.css'

export default function MaterialsPage() {
  const navigate = useNavigate()
  const { user, loading } = useAuth()
  const [materials, setMaterials] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [loadingList, setLoadingList] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [user, loading, navigate])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    async function load() {
      setLoadingList(true)
      setError('')
      try {
        const data = await documentsApi.listDocuments()
        if (!cancelled) setMaterials(data)
      } catch (_) {
        if (!cancelled) setError('Failed to load materials')
      } finally {
        if (!cancelled) setLoadingList(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [user])

  const toggleSelected = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleCreatePlan = () => {
    if (!selectedIds.length) return
    navigate('/create-plan', { state: { selectedDocumentIds: selectedIds } })
  }

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <div className={styles.card}>
          <h1 className={styles.title}>My materials</h1>
          {error && <p className={styles.error}>{error}</p>}
          {loadingList ? (
            <p className={styles.muted}>Loading materials...</p>
          ) : materials.length === 0 ? (
            <p className={styles.muted}>You have not uploaded any materials yet.</p>
          ) : (
            <>
              <ul className={styles.list}>
                {materials.map((m) => (
                  <li key={m.id} className={styles.item}>
                    <label className={styles.row}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(m.id)}
                        onChange={() => toggleSelected(m.id)}
                      />
                      <span className={styles.name}>{m.original_name}</span>
                      <span className={styles.size}>
                        {(m.file_size / (1024 * 1024)).toFixed(2)} MB
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className={styles.btn}
                onClick={handleCreatePlan}
                disabled={!selectedIds.length}
              >
                Create plan from selected
              </button>
            </>
          )}
        </div>
      </main>
    </div>
  )
}

