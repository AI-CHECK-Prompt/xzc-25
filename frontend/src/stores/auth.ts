import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('xzc25_token') || '',
    user: JSON.parse(localStorage.getItem('xzc25_user') || 'null'),
  }),
  getters: {
    role: (state) => state.user?.role,
    isAuthed: (state) => Boolean(state.token && state.user),
  },
  actions: {
    setSession(token: string, user: any) {
      this.token = token
      this.user = user
      localStorage.setItem('xzc25_token', token)
      localStorage.setItem('xzc25_user', JSON.stringify(user))
    },
    clear() {
      this.token = ''
      this.user = null
      localStorage.removeItem('xzc25_token')
      localStorage.removeItem('xzc25_user')
    },
  },
})
