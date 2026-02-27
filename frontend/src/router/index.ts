import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ImageListView from '../views/ImageListView.vue'
import ProjectListView from '../views/ProjectListView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'projects',
      component: ProjectListView,
    },
    {
      path: '/projects/:projectId',
      name: 'project-images',
      component: ImageListView,
      props: true,
    },
    {
      path: '/dev',
      name: 'dev',
      component: HomeView,
    },
  ],
})

export default router
