import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AppHeader from '../components/AppHeader'
import { plansApi } from '../api/client'
import { useAuth } from '../context/AuthContext'
import styles from './PlansPage.module.css'

export default function PlansPage() {
  const navigate = useNavigate()
  const { user, loading } = useAuth()
  const [plans, setPlans] = useState([])
  const [loadingPlans, setLoadingPlans] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [user, loading, navigate])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    async function load() {
      setLoadingPlans(true)
      setError('')
      try {
        const data = await plansApi.listPlans()
        const withProgress = await Promise.all(
          data.map(async (plan) => {
            try {
              const progress = await plansApi.getPlanProgress(plan.id)
              return {
                ...plan,
                progressPercent: Math.round(progress.plan_progress_percent || 0),
                completedUnits: progress.completed_units || 0,
                totalUnits: progress.total_units || 0,
              }
            } catch (_) {
              return {
                ...plan,
                progressPercent: 0,
                completedUnits: 0,
                totalUnits: 0,
              }
            }
          })
        )
        if (!cancelled) setPlans(withProgress)
      } catch (e) {
        if (!cancelled) setError('Failed to load plans')
      } finally {
        if (!cancelled) setLoadingPlans(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [user])

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <div className={styles.card}>
          <div className={styles.headerRow}>
            <h1 className={styles.title}>My study plans</h1>
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => navigate('/materials')}
              >
                Upload materials
              </button>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => navigate('/create-plan')}
              >
                New plan
              </button>
            </div>
          </div>
          {error && <p className={styles.error}>{error}</p>}
          {loadingPlans ? (
            <p>Loading...</p>
          ) : plans.length === 0 ? (
            <p>You have no plans yet.</p>
          ) : (
            <ul className={styles.list}>
              {plans.map((plan) => (
                <li
                  key={plan.id}
                  className={styles.item}
                  onClick={() => navigate(`/plans/${plan.id}`)}
                >
                  <h2 className={styles.planTitle}>{plan.title}</h2>
                  {plan.description && <p className={styles.planDesc}>{plan.description}</p>}
                  <p className={styles.planMeta}>
                    Status: <strong>{plan.generation_status}</strong>
                  </p>
                  <div className={styles.progressWrap}>
                    <div className={styles.progressMeta}>
                      <span>Progress</span>
                      <span>
                        {plan.completedUnits}/{plan.totalUnits} ({plan.progressPercent}%)
                      </span>
                    </div>
                    <div className={styles.progressTrack}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${plan.progressPercent}%` }}
                      />
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  )
}

