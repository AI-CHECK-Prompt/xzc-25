<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessageBox } from 'element-plus'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const role = computed(() => auth.user?.role)
const roleLabel = computed(() => {
  return {
    factory: '预制构件工厂',
    transport: '运输单位',
    contractor: '施工总承包',
    supervisor: '监理单位',
    owner: '建设单位',
    quality: '质量监督机构',
  }[role.value as string] || ''
})

const menuByRole: Record<string, { path: string; label: string; icon: string }[]> = {
  factory: [
    { path: '/factory/production', label: '构件生产录入', icon: 'Cpu' },
    { path: '/factory/outbound', label: '构件出厂登记', icon: 'Van' },
    { path: '/trace', label: '构件追溯', icon: 'Search' },
  ],
  transport: [
    { path: '/transport/telemetry', label: '运输轨迹上报', icon: 'Location' },
    { path: '/transport/alerts', label: '运输告警', icon: 'Warning' },
    { path: '/trace', label: '构件追溯', icon: 'Search' },
  ],
  contractor: [
    { path: '/site/entry', label: '构件进场登记', icon: 'Box' },
    { path: '/site/hoisting', label: '吊装登记', icon: 'SortUp' },
    { path: '/site/joint', label: '节点连接', icon: 'Connection' },
    { path: '/site/protection', label: '成品保护', icon: 'Shield' },
    { path: '/contractor/rectification', label: '整改处理', icon: 'WarningFilled' },
    { path: '/trace', label: '构件追溯', icon: 'Search' },
  ],
  supervisor: [
    { path: '/supervisor/concealed', label: '隐蔽工程验收', icon: 'View' },
    { path: '/quality/workbench', label: '质监抽检', icon: 'Aim' },
    { path: '/trace', label: '构件追溯', icon: 'Search' },
  ],
  owner: [
    { path: '/owner/dashboard', label: '项目总览', icon: 'DataLine' },
    { path: '/owner/progress', label: '项目进度可视化', icon: 'Histogram' },
    { path: '/owner/archives', label: '档案归档', icon: 'Folder' },
    { path: '/operator/maintenance', label: '维护管理', icon: 'Tools' },
    { path: '/trace', label: '构件追溯', icon: 'Search' },
  ],
  quality: [
    { path: '/quality/workbench', label: '质监工作台', icon: 'Aim' },
    { path: '/quality/mobile', label: '现场录入(移动端)', icon: 'Cellphone' },
    { path: '/quality/inspections', label: '告警 / 档案签收', icon: 'Bell' },
    { path: '/owner/progress', label: '项目进度', icon: 'Histogram' },
    { path: '/trace', label: '构件追溯', icon: 'Search' },
  ],
}

const menus = computed(() => menuByRole[role.value as string] || [])

const online = ref(navigator.onLine)
window.addEventListener('online', () => (online.value = true))
window.addEventListener('offline', () => (online.value = false))

async function logout() {
  try {
    await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
    auth.clear()
    router.replace('/login')
  } catch {}
}
</script>

<template>
  <div class="layout">
    <header class="layout-header">
      <h1>装配式建筑构件全过程质量追溯平台</h1>
      <div style="display:flex; align-items:center; gap:12px;">
        <el-tag :type="online ? 'success' : 'warning'" effect="dark">
          {{ online ? '在线' : '离线缓存中' }}
        </el-tag>
        <span>{{ auth.user?.full_name }}（{{ roleLabel }}）</span>
        <el-button size="small" type="warning" plain @click="logout">退出</el-button>
      </div>
    </header>
    <div v-if="!online" class="offline-banner">
      当前处于弱网/离线状态，操作将暂存到本地数据库，恢复网络后自动同步。
    </div>
    <div class="layout-body">
      <aside class="layout-aside">
        <el-menu
          background-color="#001529"
          text-color="#c9d1d9"
          active-text-color="#ffd04b"
          :default-active="route.path"
          router
        >
          <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
            <el-icon><component :is="m.icon" /></el-icon>
            <span>{{ m.label }}</span>
          </el-menu-item>
        </el-menu>
      </aside>
      <main class="layout-main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </main>
    </div>
  </div>
</template>
