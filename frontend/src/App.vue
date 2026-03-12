<script setup lang="ts">
import { ref, onMounted } from "vue";
import Dashboard from "./components/Dashboard.vue";
import Login from "./components/Login.vue";

const isAuthorized = ref(false);
const username = ref("");

onMounted(() => {
  const token = localStorage.getItem("token");
  if (token) {
    isAuthorized.value = true;
    username.value = localStorage.getItem("username") || "User";
  }
});

const handleLoginSuccess = () => {
  isAuthorized.value = true;
  username.value = localStorage.getItem("username") || "User";
};

const handleLogout = () => {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  isAuthorized.value = false;
};
</script>

<template>
  <div v-if="!isAuthorized">
    <Login @login-success="handleLoginSuccess" />
  </div>
  <div v-else class="min-h-screen p-4 md:p-8 bg-slate-950 text-slate-200">
    <header class="max-w-[1800px] mx-auto mb-8 flex justify-between items-center">
      <div>
        <h1
          class="text-4xl font-black bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent tracking-tighter"
        >
          Local AI Quant
        </h1>
        <p class="text-slate-500 mt-1 text-sm font-medium">
          本地 AI 量化交易仪表盘 (Vue 3 + TS + XGBoost)
        </p>
      </div>
      <div class="flex items-center gap-4">
        <div
          class="px-4 py-2 glass rounded-2xl border border-white/10 flex items-center gap-3"
        >
          <div class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
          <span
            class="text-xs font-bold text-slate-300 uppercase tracking-widest"
            >{{ username }}</span
          >
        </div>
        <button
          @click="handleLogout"
          class="p-2 hover:bg-rose-500/20 text-rose-500 rounded-xl transition-all border border-transparent hover:border-rose-500/30"
          title="退出登录"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="lucide lucide-log-out"
          >
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" x2="9" y1="12" y2="12" />
          </svg>
        </button>
      </div>
    </header>

    <main class="max-w-[1800px] mx-auto">
      <Dashboard />
    </main>
  </div>
</template>

<style>
.glass {
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
}
</style>
