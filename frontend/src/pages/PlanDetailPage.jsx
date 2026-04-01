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
  const [planProgress, setPlanProgress] = useState(null)
  const [error, setError] = useState('')
  const [loadingPlan, setLoadingPlan] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState('')
  const [contentLanguage, setContentLanguage] = useState('auto')
  const [deletingDocId, setDeletingDocId] = useState(null)
  const [docDeleteError, setDocDeleteError] = useState('')

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
        const [data, progress] = await Promise.all([
          plansApi.getPlan(id),
          plansApi.getPlanProgress(id).catch(() => null),
        ])
        if (!cancelled) {
          setPlan(data)
          if (data?.content_language) {
            setContentLanguage(data.content_language)
          }
          setPlanProgress(progress)
        }
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

  useEffect(() => {
    if (!user || !plan || plan.generation_status !== 'processing') return undefined
    const tick = async () => {
      try {
        const [data, progress] = await Promise.all([
          plansApi.getPlan(id),
          plansApi.getPlanProgress(id).catch(() => null),
        ])
        setPlan(data)
        setPlanProgress(progress)
      } catch (_) {
        /* keep last good state */
      }
    }
    void tick()
    const interval = setInterval(tick, 2500)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void tick()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [user, id, plan?.generation_status])

  const handleDeleteDocument = async (documentId) => {
    if (!id || !documentId) return
    if (!window.confirm('Delete this material from the plan? The file, embeddings and extracted topics will be removed from the database.')) {
      return
    }
    setDocDeleteError('')
    setDeletingDocId(documentId)
    try {
      await plansApi.deletePlanDocument(id, documentId)
      const [data, progress] = await Promise.all([
        plansApi.getPlan(id),
        plansApi.getPlanProgress(id).catch(() => null),
      ])
      setPlan(data)
      setPlanProgress(progress)
    } catch (e) {
      setDocDeleteError(e.body?.detail || e.message || 'Failed to delete material')
    } finally {
      setDeletingDocId(null)
    }
  }

  const handleGenerate = async () => {
    setGenerateError('')
    setGenerating(true)
    try {
      const data = await plansApi.generatePlan(id, { content_language: contentLanguage })
      setPlan(data)
      try {
        const progress = await plansApi.getPlanProgress(id).catch(() => null)
        setPlanProgress(progress)
      } catch (_) {
        /* ignore */
      }
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
          {planProgress && planProgress.total_units > 0 && (
            <div className={styles.sidebarProgress}>
              <div className={styles.sidebarProgressRow}>
                <span className={styles.sidebarProgressLabel}>Plan progress</span>
                <span className={styles.sidebarProgressValue}>
                  {planProgress.completed_units}/{planProgress.total_units} ·{' '}
                  {Math.round(planProgress.plan_progress_percent || 0)}%
                </span>
              </div>
              <div className={styles.sidebarProgressTrack}>
                <div
                  className={styles.sidebarProgressFill}
                  style={{
                    width: `${Math.round(planProgress.plan_progress_percent || 0)}%`,
                  }}
                />
              </div>
            </div>
          )}
          {loadingPlan ? (
            <p className={styles.muted}>Loading sections...</p>
          ) : error ? (
            <p className={styles.error}>{error}</p>
          ) : !plan?.sections?.length ? (
            plan?.generation_status === 'processing' ? (
              <p className={styles.muted}>
                Генерация курса… сейчас создаётся структура разделов (обычно несколько секунд).
              </p>
            ) : (
              <p className={styles.muted}>This plan has no sections yet.</p>
            )
          ) : (
            <>
              {plan.generation_status === 'processing' && (
                <p className={styles.generatingBanner}>
                  Идёт наполнение модулей (теория и вопросы). Список слева уже можно открывать — статусы
                  «…» у юнитов обновляются по мере готовности.
                </p>
              )}
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
                            {unit.generation_status === 'generating' && (
                              <span className={styles.unitMeta}> · …</span>
                            )}
                            {unit.generation_status === 'failed' && (
                              <span className={styles.unitMetaError}> · ошибка</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </>
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
              <fieldset className={styles.langFieldset}>
                <legend className={styles.langLegend}>Язык курса</legend>
                <div className={styles.langOptions}>
                  <label className={styles.langLabel}>
                    <input
                      type="radio"
                      name="content_language"
                      value="auto"
                      checked={contentLanguage === 'auto'}
                      onChange={() => setContentLanguage('auto')}
                      disabled={generating}
                    />
                    Авто (по целям и материалам)
                  </label>
                  <label className={styles.langLabel}>
                    <input
                      type="radio"
                      name="content_language"
                      value="ru"
                      checked={contentLanguage === 'ru'}
                      onChange={() => setContentLanguage('ru')}
                      disabled={generating}
                    />
                    Русский
                  </label>
                  <label className={styles.langLabel}>
                    <input
                      type="radio"
                      name="content_language"
                      value="en"
                      checked={contentLanguage === 'en'}
                      onChange={() => setContentLanguage('en')}
                      disabled={generating}
                    />
                    English
                  </label>
                </div>
              </fieldset>
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
          {plan?.documents?.length > 0 && (
            <div className={styles.materialsBlock}>
              <h2 className={styles.materialsTitle}>Materials</h2>
              <p className={styles.muted}>
                Removing a file deletes it from storage and drops all vector chunks and topic data for this document.
              </p>
              {docDeleteError && <p className={styles.error}>{docDeleteError}</p>}
              <ul className={styles.materialsList}>
                {plan.documents.map((d) => (
                  <li key={d.id} className={styles.materialRow}>
                    <span className={styles.materialName}>{d.original_name}</span>
                    <button
                      type="button"
                      className={styles.btnDanger}
                      disabled={deletingDocId === d.id}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteDocument(d.id)
                      }}
                    >
                      {deletingDocId === d.id ? 'Deleting…' : 'Remove'}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

