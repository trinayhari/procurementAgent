import { useState } from 'react'
import type { FormEvent } from 'react'
import { Box, css } from './lib'
import { login, register } from './api'
import type { AuthUser } from './api'

// Standalone auth screen shown until a valid session exists. Calls onAuthed
// with the signed-in user once login/register succeeds.
export default function Login({
  onAuthed,
}: {
  onAuthed: (user: AuthUser) => void
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isRegister = mode === 'register'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const user = isRegister
        ? await register({ email, password, name, company })
        : await login(email, password)
      onAuthed(user)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const inputStyle = css(
    'width:100%;height:40px;padding:0 12px;border-radius:9px;background:var(--panel-2);border:1px solid var(--border);color:var(--text);font-size:13.5px;outline:none',
  )
  const labelStyle = css('font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:6px;display:block')

  return (
    <div
      style={{
        ...css('min-height:100vh;background:var(--bg);color:var(--text);display:flex;align-items:center;justify-content:center;padding:24px'),
      }}
    >
      <div style={css('width:100%;max-width:400px;animation:pcUp .25s ease both')}>
        <div style={css('display:flex;align-items:center;gap:11px;justify-content:center;margin-bottom:22px')}>
          <img src="/proq-icon.png" alt="Proq" width={38} height={38} style={css('flex:none')} />
          <div style={css('display:flex;flex-direction:column;line-height:1.1')}>
            <span style={css('font-size:18px;font-weight:800;letter-spacing:-.01em')}>Proq</span>
            <span style={css('font-size:10px;font-weight:600;color:var(--text-3);letter-spacing:.04em')}>PROCUREMENT OS</span>
          </div>
        </div>

        <form
          onSubmit={submit}
          style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:24px')}
        >
          <h1 style={css('margin:0 0 4px;font-size:19px;font-weight:700;letter-spacing:-.01em')}>
            {isRegister ? 'Create your account' : 'Welcome back'}
          </h1>
          <p style={css('margin:0 0 20px;font-size:13px;color:var(--text-3)')}>
            {isRegister ? 'Start managing procurement with AI.' : 'Sign in to your workspace.'}
          </p>

          {isRegister && (
            <>
              <div style={css('margin-bottom:14px')}>
                <label style={labelStyle}>Full name</label>
                <input style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Jordan Mills" autoComplete="name" />
              </div>
              <div style={css('margin-bottom:14px')}>
                <label style={labelStyle}>Company</label>
                <input style={inputStyle} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Meridian Civil Co." autoComplete="organization" />
              </div>
            </>
          )}

          <div style={css('margin-bottom:14px')}>
            <label style={labelStyle}>Email</label>
            <input
              style={inputStyle} type="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="email"
            />
          </div>

          <div style={css('margin-bottom:18px')}>
            <label style={labelStyle}>Password</label>
            <input
              style={inputStyle} type="password" required value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isRegister ? 'At least 8 characters' : '••••••••'}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              minLength={isRegister ? 8 : undefined}
            />
          </div>

          {error && (
            <div style={css('font-size:12.5px;color:var(--danger);background:var(--danger-soft,rgba(220,38,38,.1));border:1px solid var(--danger);border-radius:9px;padding:9px 11px;margin-bottom:14px')}>
              {error}
            </div>
          )}

          <Box
            as="button" type="submit" disabled={busy}
            style={css(`width:100%;height:40px;border-radius:9px;background:var(--primary);color:var(--on-primary,#fff);font-size:14px;font-weight:600;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:var(--shadow-sm);opacity:${busy ? '.7' : '1'}`)}
            hover="background:var(--primary-2)"
          >
            {busy && <span style={css('width:15px;height:15px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;display:inline-block;animation:pcSpin .7s linear infinite')}></span>}
            {isRegister ? 'Create account' : 'Sign in'}
          </Box>

          <div style={css('margin-top:16px;text-align:center;font-size:12.5px;color:var(--text-3)')}>
            {isRegister ? 'Already have an account? ' : "Don't have an account? "}
            <Box
              as="button" type="button"
              onClick={() => { setMode(isRegister ? 'login' : 'register'); setError(null) }}
              style={css('display:inline;color:var(--primary);font-weight:600;font-size:12.5px;background:none')}
              hover="color:var(--primary-2)"
            >
              {isRegister ? 'Sign in' : 'Create one'}
            </Box>
          </div>
        </form>

        {!isRegister && (
          <p style={css('margin:14px 0 0;text-align:center;font-size:11.5px;color:var(--text-3)')}>
            Demo: jordan@meridiancivil.com · procureai
          </p>
        )}
      </div>
    </div>
  )
}
