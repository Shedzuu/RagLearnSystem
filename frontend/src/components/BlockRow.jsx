import styles from './BlockRow.module.css'

/**
 * Ряд из 3 блоков: плейсхолдер photo + текст.
 * items: [{ title?, text? }]
 */
export default function BlockRow({ items, variant = 'gray' }) {
  return (
    <div className={styles.row}>
      {items.map((item, i) => (
        <div key={i} className={styles.block}>
          <div className={variant === 'white' ? styles.placeholderWhite : styles.placeholderGray}>
            photo
          </div>
          {item.title && <p className={styles.title}>{item.title}</p>}
          {item.text && <p className={styles.text}>{item.text}</p>}
        </div>
      ))}
    </div>
  )
}
