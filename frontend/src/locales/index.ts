import { createI18n } from 'vue-i18n'
import en from './en'
import zh from './zh'

const savedLocale = localStorage.getItem('lingshu-locale') || 'zh' // Default to Chinese since it's a TCM research tool

const i18n = createI18n({
  legacy: false, // Use Composition API mode
  locale: savedLocale,
  fallbackLocale: 'en',
  messages: {
    en,
    zh,
  },
})

export default i18n

export function setLocale(locale: 'zh' | 'en') {
  i18n.global.locale.value = locale
  localStorage.setItem('lingshu-locale', locale)
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
}
