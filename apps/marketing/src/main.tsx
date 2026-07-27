import React from 'react'
import { createRoot } from 'react-dom/client'
import './ds.css'
import './index.css'
import Landing from './Landing'
import { MotionConfig } from './motion'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MotionConfig reducedMotion="user">
      <Landing />
    </MotionConfig>
  </React.StrictMode>,
)
