<script setup lang="ts">
import { ref, computed, onUnmounted } from "vue";
import {
  Mail,
  Lock,
  ShieldCheck,
  TrendingUp,
  Github,
  Send
} from "lucide-vue-next";

const emit = defineEmits(["login-success"]);

const isLogin = ref(true);
const email = ref("wangqing-w@outlook.com");
const password = ref("123456");
const code = ref("");
const errorMsg = ref("");
const isLoading = ref(false);

// 验证码倒计时逻辑
const countdown = ref(0);
let timer: any = null;

const startCountdown = () => {
  countdown.value = 60;
  timer = setInterval(() => {
    if (countdown.value > 0) {
      countdown.value--;
    } else {
      clearInterval(timer);
    }
  }, 1000);
};

onUnmounted(() => {
  if (timer) clearInterval(timer);
});

const sendCode = async () => {
  if (!email.value || !email.value.includes("@")) {
    errorMsg.value = "请输入有效的邮箱地址";
    return;
  }

  try {
    isLoading.value = true;
    errorMsg.value = "";
    const res = await fetch("/api/auth/send-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.value })
    });
    const data = await res.json();
    if (res.ok) {
      startCountdown();
      errorMsg.value = "验证码已发送，请查看控制台输出";
    } else {
      errorMsg.value = data.detail || "发送失败";
    }
  } catch (err) {
    errorMsg.value = "无法连接服务器";
  } finally {
    isLoading.value = false;
  }
};

const handleSubmit = async () => {
  if (!email.value || !password.value || (!isLogin.value && !code.value)) {
    errorMsg.value = "请填写完整信息";
    return;
  }

  errorMsg.value = "";
  isLoading.value = true;

  try {
    const endpoint = isLogin.value ? "/api/auth/login" : "/api/auth/register";
    const payload: Record<string, string> = {
      email: email.value,
      password: password.value
    };
    if (!isLogin.value) payload.code = code.value;
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (res.ok) {
      if (isLogin.value) {
        localStorage.setItem("token", data.access_token);
        localStorage.setItem("username", data.username);
        emit("login-success");
      } else {
        isLogin.value = true;
        errorMsg.value = "注册成功，请使用邮箱登录";
      }
    } else {
      errorMsg.value = data.detail || "操作失败";
    }
  } catch (err) {
    errorMsg.value = "无法连接到服务器";
  } finally {
    isLoading.value = false;
  }
};
</script>

<template>
  <div
    class="min-h-screen flex items-center justify-center p-4 bg-slate-950 relative overflow-hidden"
  >
    <!-- 背景光效 -->
    <div
      class="absolute top-1/4 left-1/4 w-96 h-96 bg-emerald-500/20 blur-[120px] rounded-full animate-pulse"
    ></div>
    <div
      class="absolute bottom-1/4 right-1/4 w-96 h-96 bg-blue-500/20 blur-[120px] rounded-full animate-pulse"
    ></div>

    <div
      class="glass w-full max-w-md p-10 rounded-[2.5rem] border border-white/10 relative z-10 backdrop-blur-3xl shadow-2xl"
    >
      <div class="flex flex-col items-center mb-8">
        <div
          class="w-16 h-16 bg-gradient-to-tr from-emerald-500 to-blue-500 rounded-2xl flex items-center justify-center shadow-xl mb-4 transform -rotate-6"
        >
          <TrendingUp class="w-8 h-8 text-white" />
        </div>
        <h1 class="text-3xl font-black text-white tracking-tighter">
          AI Quant
        </h1>
        <p
          class="text-slate-500 text-sm mt-1 uppercase tracking-widest font-bold"
        >
          {{ isLogin ? "Explorer Logic" : "Start Journey" }}
        </p>
      </div>

      <form @submit.prevent="handleSubmit" class="space-y-5">
        <!-- 邮箱输入 -->
        <div class="space-y-2">
          <label
            class="text-[10px] text-slate-500 uppercase font-bold tracking-widest px-1"
            >电子邮箱</label
          >
          <div class="relative group">
            <Mail
              class="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 group-focus-within:text-emerald-400 transition-colors"
            />
            <input
              v-model="email"
              type="email"
              placeholder="email@example.com"
              class="w-full bg-white/5 border border-white/10 rounded-2xl py-3.5 pl-12 pr-4 text-white focus:outline-none focus:border-emerald-500/50 focus:bg-white/10 transition-all placeholder:text-slate-600"
            />
          </div>
        </div>

        <!-- 验证码输入 (仅注册显示) -->
        <div v-if="!isLogin" class="space-y-2">
          <label
            class="text-[10px] text-slate-500 uppercase font-bold tracking-widest px-1"
            >验证码</label
          >
          <div class="flex gap-3">
            <div class="relative group flex-1">
              <ShieldCheck
                class="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 group-focus-within:text-orange-400 transition-colors"
              />
              <input
                v-model="code"
                type="text"
                placeholder="6-Digit Code"
                maxlength="6"
                class="w-full bg-white/5 border border-white/10 rounded-2xl py-3.5 pl-12 pr-4 text-white focus:outline-none focus:border-orange-500/50 focus:bg-white/10 transition-all placeholder:text-slate-600 font-mono tracking-widest"
              />
            </div>
            <button
              type="button"
              @click="sendCode"
              :disabled="countdown > 0 || isLoading"
              class="px-6 rounded-2xl border border-white/10 bg-white/5 text-xs font-bold text-slate-300 hover:bg-white/10 hover:text-white transition-all disabled:opacity-50 min-w-[100px]"
            >
              {{ countdown > 0 ? `${countdown}s` : "发送" }}
            </button>
          </div>
        </div>

        <!-- 密码输入 -->
        <div class="space-y-2">
          <label
            class="text-[10px] text-slate-500 uppercase font-bold tracking-widest px-1"
            >安全密码</label
          >
          <div class="relative group">
            <Lock
              class="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 group-focus-within:text-blue-400 transition-colors"
            />
            <input
              v-model="password"
              type="password"
              placeholder="••••••••"
              class="w-full bg-white/5 border border-white/10 rounded-2xl py-3.5 pl-12 pr-4 text-white focus:outline-none focus:border-blue-500/50 focus:bg-white/10 transition-all placeholder:text-slate-600"
            />
          </div>
        </div>

        <div
          v-if="errorMsg"
          class="text-rose-400 text-[10px] text-center font-bold bg-rose-500/10 py-2.5 rounded-xl border border-rose-500/20 italic animate-in fade-in zoom-in duration-300"
        >
          {{ errorMsg }}
        </div>

        <button
          type="submit"
          :disabled="isLoading"
          class="w-full bg-gradient-to-r from-emerald-500 to-blue-600 hover:from-emerald-400 hover:to-blue-500 text-white font-black py-4 rounded-2xl shadow-xl shadow-blue-500/20 transition-all active:scale-95 flex items-center justify-center gap-2 disabled:opacity-50 mt-4"
        >
          <template v-if="isLoading">
            <div
              class="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"
            ></div>
          </template>
          <template v-else>
            <Send v-if="!isLogin" class="w-4 h-4" />
            {{ isLogin ? "进入系统" : "立即注册" }}
          </template>
        </button>
      </form>

      <div
        class="mt-8 pt-8 border-t border-white/5 flex flex-col items-center gap-4"
      >
        <button
          @click="
            isLogin = !isLogin;
            errorMsg = '';
          "
          class="text-xs text-slate-400 hover:text-white transition-colors flex items-center gap-2 group"
        >
          {{ isLogin ? "还没有账号？" : "已有账号？" }}
          <span
            class="text-blue-400 font-bold underline decoration-blue-400/30 underline-offset-4 group-hover:decoration-blue-400 transition-all"
          >
            {{ isLogin ? "立即注册" : "去登录" }}
          </span>
        </button>

        <div class="flex gap-4">
          <a
            href="#"
            class="p-2.5 bg-white/5 rounded-xl border border-white/10 text-slate-500 hover:text-white hover:border-white/30 transition-all"
          >
            <Github class="w-4 h-4" />
          </a>
        </div>
      </div>
    </div>

    <!-- 装饰元素 -->
    <div
      class="absolute top-10 left-10 text-[100px] font-black text-white/5 select-none pointer-events-none tracking-tighter uppercase"
    >
      Quant
    </div>
    <div
      class="absolute bottom-10 right-10 text-[100px] font-black text-white/5 select-none pointer-events-none tracking-tighter uppercase"
    >
      Local AI
    </div>
  </div>
</template>

<style scoped>
.glass {
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
}
</style>
