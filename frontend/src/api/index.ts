/**
 * API 클라이언트 설정
 * Axios 인스턴스 + 기본 설정
 */
import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
  // FastAPI 의 list[str] 쿼리 파라미터는 ?key=a&key=b (repeat) 형식으로 받는다.
  // Axios 기본값은 ?key[]=a&key[]=b (bracket) 이므로 indexes:null 로 brackets 제거.
  paramsSerializer: { indexes: null },
})

// 요청 인터셉터 (향후 인증 토큰 추가 등)
api.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
)

// 응답 인터셉터 (에러 처리)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || '알 수 없는 오류'
    console.error('API Error:', message)
    return Promise.reject(error)
  }
)

export default api
