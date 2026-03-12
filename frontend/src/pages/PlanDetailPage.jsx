import { useEffect, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import AppHeader from '../components/AppHeader'
import { useAuth } from '../context/AuthContext'
import { plansApi } from '../api/client'
import styles from './PlanDetailPage.module.css'

export default function PlanDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user, loading } = useAuth()
  const [plan, setPlan] = useState(null)
  const [error, setError] = useState('')
  const [loadingPlan, setLoadingPlan] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState('')

  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [user, loading, navigate])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    async function load() {
      setLoadingPlan(true)
      setError('')
      try {
        const data = await plansApi.getPlan(id)
        if (!cancelled) setPlan(data)
      } catch (e) {
        if (!cancelled) setError('Failed to load plan')
      } finally {
        if (!cancelled) setLoadingPlan(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [id, user])

  const handleGenerate = async () => {
    setGenerateError('')
    setGenerating(true)
    try {
      const data = await plansApi.generatePlan(id)
      setPlan(data)
    } catch (e) {
      setGenerateError(e.body?.detail || e.message || 'Generation failed')
    } finally {
      setGenerating(false)
    }
  }

  const canGenerate = plan && !generating && plan.generation_status !== 'processing'
  const showGenerateButton =
    canGenerate &&
    (plan.sections.length === 0 || plan.generation_status === 'failed')

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <div className={styles.sidebar}>
          <h2 className={styles.sidebarTitle}>{plan ? plan.title : 'Plan'}</h2>
          {loadingPlan ? (
            <p className={styles.muted}>Loading sections...</p>
          ) : error ? (
            <p className={styles.error}>{error}</p>
          ) : plan?.generation_status === 'processing' ? (
            <p className={styles.muted}>Generating course...</p>
          ) : !plan?.sections?.length ? (
            <p className={styles.muted}>This plan has no sections yet.</p>
          ) : (
            <ul className={styles.sectionList}>
              {plan.sections.map((section) => (
                <li key={section.id} className={styles.sectionItem}>
                  <div className={styles.sectionTitle}>{section.title}</div>
                  {section.units.length > 0 && (
                    <ul className={styles.unitList}>
                      {section.units.map((unit) => (
                        <li key={unit.id}>
                          <Link className={styles.unitLink} to={`/units/${unit.id}`}>
                            {unit.title}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={styles.content}>
          <h1 className={styles.title}>Plan overview</h1>
          <p className={styles.muted}>
            Select a unit on the left to start learning this plan.
          </p>
          {plan && plan.description && (
            <p className={styles.description}>{plan.description}</p>
          )}
          {showGenerateButton && (
            <div className={styles.generateBlock}>
              <button
                type="button"
                className={styles.btn}
                onClick={handleGenerate}
                disabled={generating}
              >
                {generating ? 'Generating…' : 'Generate course'}
              </button>
              <p className={styles.generateHint}>
                Build sections, theory and questions from the attached materials and your goals.
              </p>
            </div>
          )}
          {generateError && (
            <p className={styles.error}>{generateError}</p>
          )}
        </div>
      </main>
    </div>
  )
}

