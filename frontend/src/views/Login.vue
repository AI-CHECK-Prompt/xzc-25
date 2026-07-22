<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'

const router = useRouter()
const auth = useAuthStore()

const form = ref({ username: 'factory01', password: '123456' })
const loading = ref(false)

const presets = [
  { username: 'factory01', label: '预制构件工厂' },
  { username: 'transport01', label: '运输单位' },
  { username: 'contractor01', label: '施工总承包' },
  { username: 'supervisor01', label: '监理单位' },
  { username: 'owner01', label: '建设单位' },
  { username: 'quality01', label: '质量监督机构' },
]

async function submit() {
  loading.value = true
  try {
    const r = await authApi.login(form.value.username, form.value.password)
    auth.setSession(r.data.access_token, r.data.user)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e) {
    // 拦截器已处理
  } finally {
    loading.value = false
  }
}

function pick(p: { username: string }) {
  form.value.username = p.username
  form.value.password = '123456'
}

onMounted(() => {
  if (auth.isAuthed) router.replace('/')
})
</script>

<template>
  <div class="login-bg">
    <div class="login-card">
      <h2 class="title">装配式建筑构件追溯平台</h2>
      <p class="subtitle">六方协同 · 构件全过程质量可追溯</p>
      <el-form @submit.prevent="submit" :model="form" label-width="0">
        <el-form-item>
          <el-input v-model="form.username" placeholder="账号" size="large" prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" placeholder="密码" type="password" size="large" prefix-icon="Lock" show-password />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" native-type="submit" style="width:100%;">登录</el-button>
      </el-form>
      <div class="presets">
        <div class="preset-title">快速选择参与方（默认密码 123456）：</div>
        <el-tag
          v-for="p in presets"
          :key="p.username"
          :type="form.username === p.username ? 'primary' : 'info'"
          @click="pick(p)"
          style="margin: 4px; cursor: pointer;"
        >
          {{ p.label }}（{{ p.username }}）
        </el-tag>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-bg {
  height: 100vh;
  background: linear-gradient(135deg, #1d4ed8 0%, #06b6d4 100%);
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-card {
  background: #fff;
  width: 420px;
  padding: 32px;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.2);
}
.title {
  margin: 0 0 4px;
  text-align: center;
  color: #1d4ed8;
}
.subtitle {
  text-align: center;
  color: #606266;
  margin: 0 0 24px;
  font-size: 13px;
}
.presets {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed #dcdfe6;
}
.preset-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
</style>
