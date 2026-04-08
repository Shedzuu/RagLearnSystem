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
  const [uploading, setUploading] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
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
    const interval = setInterval(load, 5000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [user])

  const statusLabel = (m) => {
    const indexMap = {
      pending: 'Reading: queued',
      processing: 'Reading: in progress',
      ready: 'Reading: done',
      failed: 'Reading: failed',
    }
    const topicsMap = {
      idle: 'Topics: not started',
      processing: 'Topics: in progress',
      ready: 'Topics: done',
      failed: 'Topics: failed',
    }
    return `${indexMap[m.index_status] || 'Reading: unknown'} · ${topicsMap[m.topics_status] || 'Topics: unknown'}`
  }

  const toggleSelected = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleCreatePlan = () => {
    if (!selectedIds.length) return
    navigate('/create-plan', { state: { selectedDocumentIds: selectedIds } })
  }

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file || uploading) return
    setUploading(true)
    setError('')
    try {
      await documentsApi.uploadDocument(file)
      const data = await documentsApi.listDocuments()
      setMaterials(data)
    } catch (_) {
      setError('Failed to upload material')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleDelete = async (documentId) => {
    if (!documentId || deletingId) return
    if (!window.confirm('Delete this material? This removes the file, chunks and extracted topics.')) {
      return
    }
    setError('')
    setDeletingId(documentId)
    try {
      await documentsApi.deleteDocument(documentId)
      setSelectedIds((prev) => prev.filter((id) => id !== documentId))
      const data = await documentsApi.listDocuments()
      setMaterials(data)
    } catch (_) {
      setError('Failed to delete material')
    } finally {
      setDeletingId(null)
    }
  }

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <div className={styles.card}>
          <div className={styles.headerRow}>
            <h1 className={styles.title}>My materials</h1>
            <label className={styles.uploadBtn}>
              {uploading ? 'Uploading...' : 'Upload file'}
              <input
                type="file"
                className={styles.hiddenInput}
                onChange={handleUpload}
                disabled={uploading}
              />
            </label>
          </div>
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
                    <div className={styles.row}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(m.id)}
                        onChange={() => toggleSelected(m.id)}
                      />
                      <span className={styles.name}>{m.original_name}</span>
                      <span className={styles.status}>{statusLabel(m)}</span>
                      <span className={styles.size}>
                        {(m.file_size / (1024 * 1024)).toFixed(2)} MB
                      </span>
                      <button
                        type="button"
                        className={styles.deleteBtn}
                        disabled={deletingId === m.id}
                        onClick={() => handleDelete(m.id)}
                      >
                        {deletingId === m.id ? 'Deleting...' : 'Delete'}
                      </button>
                    </div>
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

