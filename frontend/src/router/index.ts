import { createRouter, createWebHistory } from 'vue-router'
import ProjectsView from '../views/projects/ProjectsView.vue'
import ProjectLayout from '../views/projects/ProjectLayout.vue'
import ProjectOverviewView from '../views/projects/ProjectOverviewView.vue'
import ProjectDataView from '../views/projects/ProjectDataView.vue'
import ProjectAnnotateView from '../views/projects/ProjectAnnotateView.vue'
import ProjectTrainView from '../views/projects/ProjectTrainView.vue'
import ProjectEvaluateView from '../views/projects/ProjectEvaluateView.vue'
import ProjectSettingsView from '../views/projects/ProjectSettingsView.vue'
import DiagnosticsView from '../views/system/DiagnosticsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      name: 'projects',
      path: '/',
      redirect: '/projects',
    },
    {
      path: '/projects',
      component: ProjectsView,
    },
    {
      path: '/projects/:projectId',
      component: ProjectLayout,
      props: true,
      children: [
        {
          path: '',
          redirect: (to) => `/projects/${String(to.params.projectId)}/overview`,
        },
        {
          path: 'overview',
          name: 'project-overview',
          component: ProjectOverviewView,
          props: true,
        },
        {
          path: 'data',
          name: 'project-data',
          component: ProjectDataView,
          props: true,
        },
        {
          path: 'annotate',
          name: 'project-annotate',
          component: ProjectAnnotateView,
          props: true,
        },
        {
          path: 'train',
          name: 'project-train',
          component: ProjectTrainView,
          props: true,
        },
        {
          path: 'evaluate',
          name: 'project-evaluate',
          component: ProjectEvaluateView,
          props: true,
        },
        {
          path: 'settings',
          name: 'project-settings',
          component: ProjectSettingsView,
          props: true,
        },
      ],
    },
    {
      path: '/diagnostics',
      name: 'diagnostics',
      component: DiagnosticsView,
    },
  ],
})

export default router
