import { createApp } from "vue";

import App from "./App.vue";
import i18n from "./locales";
import "./style.css";

const app = createApp(App);
app.use(i18n);
app.mount("#app");

// Set initial html lang attribute
document.documentElement.lang = i18n.global.locale.value === 'zh' ? 'zh-CN' : 'en';

