import { useState } from 'react'
import styles from './ReviewsSlider.module.css'

const ITEMS_PER_VIEW = 3

export default function ReviewsSlider({ items }) {
  const [current, setCurrent] = useState(0)
  const totalSlides = Math.ceil(items.length / ITEMS_PER_VIEW)

  const go = (dir) => {
    setCurrent((prev) => {
      const next = prev + dir
      if (next < 0) return totalSlides - 1
      if (next >= totalSlides) return 0
      return next
    })
  }

  const visibleItems = items.slice(
    current * ITEMS_PER_VIEW,
    current * ITEMS_PER_VIEW + ITEMS_PER_VIEW
  )

  return (
    <div className={styles.slider}>
      <div className={styles.row}>
        {visibleItems.map((item, i) => (
          <div key={i} className={styles.block}>
            <div className={styles.placeholder}>
              {item.image ? (
                <img src={item.image} alt={item.title} className={styles.image} />
              ) : (
                <span className={styles.fallback}>photo</span>
              )}
            </div>
            <div className={styles.metaRow}>
              <p className={styles.title}>{item.title}</p>
              {item.meta && <span className={styles.meta}>{item.meta}</span>}
            </div>
            <p className={styles.text}>{item.text}</p>
          </div>
        ))}
      </div>
      {totalSlides > 1 && (
        <>
          <button type="button" className={styles.arrow} onClick={() => go(-1)} aria-label="Previous">
            ‹
          </button>
          <button type="button" className={styles.arrowRight} onClick={() => go(1)} aria-label="Next">
            ›
          </button>
          <div className={styles.dots}>
            {Array.from({ length: totalSlides }).map((_, i) => (
              <button
                key={i}
                type="button"
                className={i === current ? styles.dotActive : styles.dot}
                onClick={() => setCurrent(i)}
                aria-label={`Slide ${i + 1}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
