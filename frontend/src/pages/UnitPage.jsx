import { useEffect, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import AppHeader from '../components/AppHeader'
import { useAuth } from '../context/AuthContext'
import { plansApi } from '../api/client'
import styles from './UnitPage.module.css'

function getUnitStateKey(planId, unitId) {
  return `diploma_unit_state_${planId}_${unitId}`
}

function readUnitState(planId, unitId) {
  if (!planId || !unitId) return null
  try {
    const raw = localStorage.getItem(getUnitStateKey(planId, unitId))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') return parsed
    return null
  } catch (_) {
    return null
  }
}

function writeUnitState(planId, unitId, state) {
  if (!planId || !unitId) return
  try {
    localStorage.setItem(getUnitStateKey(planId, unitId), JSON.stringify(state))
  } catch (_) {
    // ignore quota/storage errors
  }
}

export default function UnitPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user, loading } = useAuth()
  const [unit, setUnit] = useState(null)
  const [plan, setPlan] = useState(null)
  const [attemptId, setAttemptId] = useState(null)
  const [answersState, setAnswersState] = useState({})
  const [unitResult, setUnitResult] = useState(null)
  const [hasFinished, setHasFinished] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [loadingUnit, setLoadingUnit] = useState(true)
  const [loadingPlan, setLoadingPlan] = useState(false)

  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [user, loading, navigate])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    async function load() {
      setLoadingUnit(true)
      setError('')
      try {
        const data = await plansApi.getUnit(id)
        if (cancelled) return
        setUnit(data)
        const cachedState = readUnitState(data.plan_id, data.id)
        if (cachedState && cachedState.unitId === data.id) {
          setAnswersState(cachedState.answersState || {})
          setUnitResult(cachedState.unitResult || null)
          setHasFinished(Boolean(cachedState.hasFinished))
          setAttemptId(cachedState.attemptId || null)
        } else {
          setAnswersState({})
          setUnitResult(null)
          setHasFinished(false)
          setAttemptId(null)
        }

        // Запрашиваем попытку только если секция ещё не завершена.
        if (!cachedState?.hasFinished || !cachedState?.attemptId) {
          const attempt = await plansApi.startAttempt(data.plan_id)
          if (!cancelled) setAttemptId(attempt.attempt_id)
        }
      } catch (e) {
        if (!cancelled) setError('Failed to load unit')
      } finally {
        if (!cancelled) setLoadingUnit(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [id, user])

  // Load full plan structure for sidebar navigation once we know plan_id
  useEffect(() => {
    if (!user || !unit?.plan_id) return
    let cancelled = false
    async function loadPlan() {
      setLoadingPlan(true)
      try {
        const fullPlan = await plansApi.getPlan(unit.plan_id)
        if (!cancelled) setPlan(fullPlan)
      } catch (_) {
        // Навбар — вспомогательная часть, можно молча проигнорировать ошибку
      } finally {
        if (!cancelled) setLoadingPlan(false)
      }
    }
    loadPlan()
    return () => {
      cancelled = true
    }
  }, [user, unit])

  // Персистим состояние текущей секции, чтобы ответы и результат не исчезали.
  useEffect(() => {
    if (!unit) return
    writeUnitState(unit.plan_id, unit.id, {
      unitId: unit.id,
      attemptId,
      answersState,
      unitResult,
      hasFinished,
    })
  }, [unit, attemptId, answersState, unitResult, hasFinished])

  const updateAnswerState = (questionId, update) => {
    setAnswersState((prev) => ({
      ...prev,
      [questionId]: { ...(prev[questionId] || {}), ...update },
    }))
  }

  const toggleChoice = (question, choiceId) => {
    const qState = answersState[question.id] || {}
    const current = qState.selectedChoices || []
    if (question.type === 'single_choice') {
      updateAnswerState(question.id, { selectedChoices: [choiceId] })
    } else if (question.type === 'multiple_choice') {
      const exists = current.includes(choiceId)
      const next = exists ? current.filter((id2) => id2 !== choiceId) : [...current, choiceId]
      updateAnswerState(question.id, { selectedChoices: next })
    }
  }

  const handleSubmitUnit = async () => {
    if (!attemptId || !unit || !unit.questions.length || submitting) return
    setSubmitting(true)
    setError('')
    try {
      const results = await Promise.all(
        unit.questions.map(async (question) => {
          const qState = answersState[question.id] || {}
          const payload = {
            attempt_id: attemptId,
            question_id: question.id,
            text_answer: qState.textAnswer || '',
            code_answer: qState.codeAnswer || '',
            selected_choices: (qState.selectedChoices || []).map((choiceId) => ({
              choice_id: choiceId,
            })),
          }
          const result = await plansApi.submitAnswer(payload)
          updateAnswerState(question.id, {
            lastResult: {
              is_correct: result.is_correct,
              earned_points: result.earned_points,
              feedback_text: result.feedback_text || '',
              correct_answer: result.correct_answer || '',
            },
          })
          return { question, result }
        })
      )

      const totalQuestions = unit.questions.length
      const correctCount = results.filter((r) => r.result.is_correct).length
      const earnedPoints = results.reduce(
        (sum, r) => sum + (r.result.earned_points || 0),
        0
      )
      const maxPoints = unit.questions.reduce((sum, q) => sum + (q.points || 0), 0)
      const scorePercent = maxPoints > 0 ? (earnedPoints / maxPoints) * 100 : 0

      const summary = await plansApi.finishAttempt(attemptId, {
        unitId: unit.id,
        sectionId: unit.section_id,
      })

      setUnitResult({
        unitId: unit.id,
        scorePercent: summary.score_percent ?? scorePercent,
        correctCount: summary.correct_count ?? correctCount,
        totalQuestions: summary.total_questions ?? totalQuestions,
        earnedPoints: summary.earned_points ?? earnedPoints,
        maxPoints: summary.max_points ?? maxPoints,
        raw: summary,
      })
      setHasFinished(true)
    } catch (e) {
      setError('Failed to submit unit answers')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRetryUnit = async () => {
    if (!user || !unit) return
    setSubmitting(true)
    setError('')
    try {
      const attempt = await plansApi.startAttempt(unit.plan_id)
      setAttemptId(attempt.attempt_id)
      setAnswersState({})
      setUnitResult(null)
      setHasFinished(false)
      writeUnitState(unit.plan_id, unit.id, {
        unitId: unit.id,
        attemptId: attempt.attempt_id,
        answersState: {},
        unitResult: null,
        hasFinished: false,
      })
    } catch (e) {
      setError('Failed to start a new attempt')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading || !user) return null

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <aside className={styles.sidebar}>
          <h2 className={styles.sidebarTitle}>{plan ? plan.title : 'Plan'}</h2>
          {loadingPlan || !plan ? (
            <p className={styles.muted}>Loading navigation...</p>
          ) : !plan.sections.length ? (
            <p className={styles.muted}>This plan has no sections yet.</p>
          ) : (
            <ul className={styles.sectionList}>
              {plan.sections.map((section) => (
                <li key={section.id} className={styles.sectionItem}>
                  <div className={styles.sectionTitle}>{section.title}</div>
                  {section.units.length > 0 && (
                    <ul className={styles.unitList}>
                      {section.units.map((u) => (
                        <li key={u.id}>
                          <Link
                            className={
                              u.id.toString() === id ? styles.unitLinkActive : styles.unitLink
                            }
                            to={`/units/${u.id}`}
                          >
                            {u.title}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className={styles.content}>
          {loadingUnit ? (
            <p className={styles.muted}>Loading unit...</p>
          ) : error ? (
            <p className={styles.error}>{error}</p>
          ) : !unit ? (
            <p className={styles.error}>Unit not found.</p>
          ) : (
            <>
              <h1 className={styles.title}>{unit.title}</h1>
              <section className={styles.theory}>
                <h2 className={styles.sectionTitle}>Theory</h2>
                <p className={styles.theoryText}>{unit.theory}</p>
              </section>
              {unit.questions.length > 0 && (
                <section className={styles.questions}>
                  <h2 className={styles.sectionTitle}>Questions</h2>
                  <ul className={styles.questionList}>
                    {unit.questions.map((q) => {
                      const qState = answersState[q.id] || {}
                      return (
                        <li key={q.id} className={styles.questionItem}>
                          <p className={styles.questionText}>{q.text}</p>
                          {q.type === 'single_choice' || q.type === 'multiple_choice' ? (
                            <ul className={styles.choiceList}>
                              {q.choices.map((ch) => {
                                const selected = (qState.selectedChoices || []).includes(ch.id)
                                return (
                                  <li key={ch.id}>
                                    <label className={styles.choiceLabel}>
                                      <input
                                        type={q.type === 'single_choice' ? 'radio' : 'checkbox'}
                                        name={`q-${q.id}`}
                                        checked={selected}
                                        onChange={() => toggleChoice(q, ch.id)}
                                      />
                                      <span>{ch.text}</span>
                                    </label>
                                  </li>
                                )
                              })}
                            </ul>
                          ) : (
                            <textarea
                              className={styles.textarea}
                              rows={3}
                              placeholder={
                                q.type === 'code'
                                  ? 'Write your code here...'
                                  : 'Write your answer here...'
                              }
                              value={q.type === 'code' ? qState.codeAnswer || '' : qState.textAnswer || ''}
                              onChange={(e) =>
                                updateAnswerState(q.id, q.type === 'code' ? { codeAnswer: e.target.value } : { textAnswer: e.target.value })
                              }
                            />
                          )}
                          {qState.lastResult && (
                            <>
                              <p
                                className={
                                  qState.lastResult.error
                                    ? styles.error
                                    : qState.lastResult.is_correct
                                    ? styles.correct
                                    : styles.incorrect
                                }
                              >
                                {qState.lastResult.error
                                  ? qState.lastResult.error
                                  : qState.lastResult.is_correct
                                  ? 'Correct!'
                                  : 'Incorrect.'}
                              </p>
                              {qState.lastResult.correct_answer && (
                                <div className={styles.feedbackBox}>
                                  <div className={styles.feedbackTitle}>Correct answer</div>
                                  <pre className={styles.feedbackPre}>{qState.lastResult.correct_answer}</pre>
                                </div>
                              )}
                              {qState.lastResult.feedback_text && (
                                <div className={styles.feedbackBox}>
                                  <div className={styles.feedbackTitle}>Feedback</div>
                                  <p className={styles.feedbackText}>{qState.lastResult.feedback_text}</p>
                                </div>
                              )}
                            </>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                  <div className={styles.unitActions}>
                    {!hasFinished ? (
                      <button
                        type="button"
                        className={styles.submitBtnPrimary}
                        onClick={handleSubmitUnit}
                        disabled={!attemptId || submitting}
                      >
                        {submitting ? 'Submitting...' : 'Submit answers'}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className={styles.retryBtn}
                        onClick={handleRetryUnit}
                        disabled={submitting}
                      >
                        {submitting ? 'Starting...' : 'Retry unit'}
                      </button>
                    )}
                    {unitResult && unitResult.unitId === unit.id && (
                      <div className={styles.unitResult}>
                        <div className={styles.unitResultHeader}>Unit result</div>
                        <div className={styles.unitResultScore}>
                          You scored{' '}
                          <strong>
                            {Math.round(unitResult.earnedPoints * 10) / 10}/
                            {Math.round(unitResult.maxPoints * 10) / 10}
                          </strong>{' '}
                          ({Math.round(unitResult.scorePercent)}%)
                        </div>
                        <div className={styles.unitResultMeta}>
                          Correct {unitResult.correctCount} out of{' '}
                          {unitResult.totalQuestions}
                        </div>
                        <div
                          className={
                            unitResult.scorePercent >= 70
                              ? styles.unitResultPassed
                              : styles.unitResultTryAgain
                          }
                        >
                          {unitResult.scorePercent >= 70
                            ? 'Passed'
                            : 'Try again'}
                        </div>
                      </div>
                    )}
                  </div>
                </section>
              )}
            </>
          )}
        </section>
      </main>
    </div>
  )
}

