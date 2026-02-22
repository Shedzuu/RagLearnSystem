import { useState } from 'react'
import styles from './Slider.module.css'

/**
 * Универсальный слайдер. Принимает массив слайдов { imagePlaceholder?, title?, text? }.
 * imagePlaceholder — можно передать индекс или ключ для плейсхолдера.
 */
export default function Slider({ slides, className = '' }) {
  const [current, setCurrent] = useState(0)
  const total = slides.length

  const go = (dir) => {
    setCurrent((prev) => {
      const next = prev + dir
      if (next < 0) return total - 1
      if (next >= total) return 0
      return next
    })
  }

  return (
    <div className={`${styles.slider} ${className}`}>
      <div className={styles.track}>
        {slides.map((slide, i) => (
          <div
            key={i}
            className={styles.slide}
            style={{ transform: `translateX(${-current * 100}%)` }}
          >
            <div className={styles.placeholder}>
              {/* Плейсхолдер вместо фото */}
            </div>
            {slide.title && <h3 className={styles.title}>{slide.title}</h3>}
            {slide.text && <p className={styles.text}>{slide.text}</p>}
          </div>
        ))}
      </div>
      {total > 1 && (
        <>
          <button type="button" className={styles.arrow} onClick={() => go(-1)} aria-label="Назад">
            ‹
          </button>
          <button type="button" className={styles.arrowRight} onClick={() => go(1)} aria-label="Вперёд">
            ›
          </button>
          <div className={styles.dots}>
            {slides.map((_, i) => (
              <button
                key={i}
                type="button"
                className={i === current ? styles.dotActive : styles.dot}
                onClick={() => setCurrent(i)}
                aria-label={`Слайд ${i + 1}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
