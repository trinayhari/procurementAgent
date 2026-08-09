import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Box, css } from './lib'
import { previewInvite, acceptInvite } from './api'
import type { InvitePreview } from './api'

// Standalone screen for the public invite link (#/invite/<token>). Previews the
// invitation, then lets the invitee set a name + password to join the inviting
// org. On success it reloads into the app so the new session hydrates cleanly.
export default function AcceptInvite({
  token,
  onDismiss,
}: {
  token: string
  onDismiss: () => void
}) {
  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    previewInvite(token)
      .then((p) => { if (alive) setPreview(p) })
      .catch(() => { if (alive) setPreview({ valid: false, reason: 'unknown' } as InvitePreview) })
    return () => { alive = false }
  }, [token])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await acceptInvite(token, { name, password })
      // Land in a freshly-bootstrapped session (data hydrates with the token).
      window.location.hash = '#/dashboard'
      window.location.reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not accept the invitation.')
      setBusy(false)
    }
  }

  const inputStyle = css(
    'width:100%;height:40px;padding:0 12px;border-radius:9px;background:var(--panel-2);border:1px solid var(--border);color:var(--text);font-size:13.5px;outline:none',
  )
  const labelStyle = css('font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:6px;display:block')

  const invalidReason = (reason?: string | null): string => {
    switch (reason) {
      case 'expired': return 'This invitation has expired. Ask your teammate to send a new one.'
      case 'revoked': return 'This invitation was cancelled.'
      case 'used': return 'This invitation has already been used. Try signing in instead.'
      default: return "This invitation link isn't valid."
    }
  }

  return (
    <div style={css('min-height:100vh;background:var(--bg);color:var(--text);display:flex;align-items:center;justify-content:center;padding:24px')}>
      <div style={css('width:100%;max-width:400px;animation:pcUp .25s ease both')}>
        <div style={css('display:flex;align-items:center;gap:11px;justify-content:center;margin-bottom:22px')}>
          <img src="/proq-icon.png" alt="Proq" width={38} height={38} style={css('flex:none')} />
          <span style={css('font-size:18px;font-weight:800;letter-spacing:-.01em')}>Proq</span>
        </div>

        {preview === null ? (
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:24px;text-align:center;color:var(--text-3);font-size:13px')}>
            Checking your invitation…
          </div>
        ) : !preview.valid ? (
          <div style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:24px')}>
            <h1 style={css('margin:0 0 4px;font-size:19px;font-weight:700;letter-spacing:-.01em')}>Invitation unavailable</h1>
            <p style={css('margin:0 0 18px;font-size:13px;color:var(--text-3)')}>{invalidReason(preview.reason)}</p>
            <Box
              as="button" type="button" onClick={onDismiss}
              style={css('width:100%;height:40px;border-radius:9px;background:var(--primary);color:var(--on-primary,#fff);font-size:14px;font-weight:600;display:flex;align-items:center;justify-content:center')}
              hover="background:var(--primary-2)"
            >
              Go to sign in
            </Box>
          </div>
        ) : (
          <form
            onSubmit={submit}
            style={css('background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow-sm);padding:24px')}
          >
            <h1 style={css('margin:0 0 4px;font-size:19px;font-weight:700;letter-spacing:-.01em')}>
              Join {preview.organizationName || 'the team'}
            </h1>
            <p style={css('margin:0 0 20px;font-size:13px;color:var(--text-3)')}>
              You were invited as <strong style={css('color:var(--text-2)')}>{preview.email}</strong>. Set a password to join.
            </p>

            <div style={css('margin-bottom:14px')}>
              <label style={labelStyle}>Full name</label>
              <input style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Jordan Mills" autoComplete="name" />
            </div>

            <div style={css('margin-bottom:18px')}>
              <label style={labelStyle}>Password</label>
              <input
                style={inputStyle} type="password" required value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters" autoComplete="new-password" minLength={8}
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
              Join {preview.organizationName || 'team'}
            </Box>
          </form>
        )}
      </div>
    </div>
  )
}
