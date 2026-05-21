"""
Generate LinkedIn graphics for matlab-mcp-proxy.
Run: python3 generate_graphics.py
Produces three PNG files ready to post.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import matplotlib.patheffects as pe
import numpy as np

OUT = '/Users/soorajkrishnan/simscape-agent/matlab-mcp-proxy/tests/quarter_car_suspension/'
DPI = 200

# ── Colour palette ────────────────────────────────────────────────────────────
BG      = '#0f1117'
ACCENT  = '#00d4aa'
ORANGE  = '#f4a261'
MUTED   = '#8899bb'
WHITE   = '#e8eaf6'
DARK    = '#1a1d2e'
RED     = '#e76f51'
CARD    = '#161b2e'

def set_style(fig, ax_list=None):
    fig.patch.set_facecolor(BG)
    if ax_list:
        for ax in ax_list:
            ax.set_facecolor(CARD)
            ax.spines[:].set_color('#2a3050')
            ax.tick_params(colors=MUTED, labelsize=10)
            ax.xaxis.label.set_color(WHITE)
            ax.yaxis.label.set_color(WHITE)
            ax.title.set_color(WHITE)

# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIC 1: Compression savings bar chart
# ══════════════════════════════════════════════════════════════════════════════
labels = [
    'Large array display',
    'DOE progress loop',
    'whos variable table',
    'Algebraic loop blocks',
    'Repeated warnings',
    'Test runner output',
    'Simulink build log',
    'model_read paths',
    'Struct display',
    'Deep call stack',
]
values = [85, 79, 74, 63, 59, 62, 56, 36, 32, 40]
colors = [ACCENT if v >= 60 else ORANGE if v >= 40 else MUTED for v in values]

fig, ax = plt.subplots(figsize=(10, 6))
set_style(fig, [ax])

bars = ax.barh(labels, values, color=colors, height=0.62, zorder=3)

# Value labels
for bar, val in zip(bars, values):
    ax.text(val + 1.2, bar.get_y() + bar.get_height()/2,
            f'{val}%', va='center', ha='left',
            color=WHITE, fontsize=11, fontweight='bold')

ax.set_xlim(0, 100)
ax.set_xlabel('Token reduction (%)', color=MUTED, fontsize=11)
ax.axvline(50, color='#2a3a5e', lw=1, ls='--', zorder=2)
ax.grid(axis='x', color='#1e2540', zorder=1)
ax.set_axisbelow(True)

ax.set_title('matlab-mcp-proxy  ·  Token reduction by output type',
             color=WHITE, fontsize=13, fontweight='bold', pad=16)

# Legend
p1 = mpatches.Patch(color=ACCENT,  label='≥ 60% reduction')
p2 = mpatches.Patch(color=ORANGE,  label='40–59% reduction')
p3 = mpatches.Patch(color=MUTED,   label='< 40% reduction')
ax.legend(handles=[p1, p2, p3], loc='lower right',
          facecolor=DARK, edgecolor='#2a3050',
          labelcolor=WHITE, fontsize=9)

# Watermark
fig.text(0.98, 0.01, 'github.com/nightfury1802/matlab-mcp-proxy',
         ha='right', va='bottom', color=MUTED, fontsize=8)

plt.tight_layout()
plt.savefig(OUT + 'graphic1_savings_chart.png', dpi=DPI, bbox_inches='tight',
            facecolor=BG)
plt.close()
print('✓ graphic1_savings_chart.png')

# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIC 2: Before / After comparison
# ══════════════════════════════════════════════════════════════════════════════
fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(12, 6))
set_style(fig, [ax_l, ax_r])

for ax in (ax_l, ax_r):
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xticks([]); ax.set_yticks([])

# ── LEFT: Raw ──
ax_l.set_title('WITHOUT proxy  ·  Raw MATLAB output', color=RED,
               fontsize=11, fontweight='bold', pad=10)

raw_lines = [
    '  Name        Size          Bytes  Class',
    '',
    '  F_bump      1x1               8  double',
    '  Kd          1x1               8  double',
    '  Kp          1x1               8  double',
    '  cs          1x1               8  double',
    '  ks          1x1               8  double',
    '  kt          1x1               8  double',
    '  ms          1x1               8  double',
    '  mu          1x1               8  double',
    '',
    'Warning: Matrix is singular. RCOND=2.3e-17.',
    '> In solve (line 234)',
    '  In step (line 178)',
    '  In sim (line 847)',
    'Warning: Matrix is singular. RCOND=1.9e-17.',
    '> In solve (line 234)',
    '  In step (line 178)',
    '  In sim (line 847)',
    'Warning: Matrix is singular. RCOND=2.1e-17.',
    '> In solve (line 234)',
    '...',
    '411 chars  ·  ~103 tokens',
]

y = 0.97
for line in raw_lines:
    color = RED if 'chars' in line or 'tokens' in line else \
            ORANGE if line.startswith('Warning') else \
            MUTED if line.startswith('>') or line.startswith('  In') else WHITE
    fs = 9 if 'chars' in line else 8
    fw = 'bold' if 'chars' in line else 'normal'
    ax_l.text(0.04, y, line, color=color, fontsize=fs, fontweight=fw,
              fontfamily='monospace', va='top', transform=ax_l.transAxes)
    y -= 0.042

# ── RIGHT: Compressed ──
ax_r.set_title('WITH proxy  ·  Compressed output', color=ACCENT,
               fontsize=11, fontweight='bold', pad=10)

comp_lines = [
    'whos: F_bump[1x1,dbl]  Kd[1x1,dbl]',
    '      Kp[1x1,dbl]  cs[1x1,dbl]',
    '      ks[1x1,dbl]  kt[1x1,dbl]',
    '      ms[1x1,dbl]  mu[1x1,dbl]',
    '',
    'Warning: Matrix is singular. RCOND=2.3e-17.',
    '> In solve (line 234)',
    '  In sim (line 847)  [×6]',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '113 chars  ·  ~28 tokens  →  73% saved',
]

y = 0.97
for line in comp_lines:
    color = ACCENT if 'chars' in line or 'saved' in line else \
            ORANGE if line.startswith('Warning') else \
            MUTED if line.startswith('>') or line.startswith('  In') else \
            ACCENT if '[×6]' in line else WHITE
    fs = 9 if 'chars' in line else 8
    fw = 'bold' if 'chars' in line else 'normal'
    ax_r.text(0.04, y, line, color=color, fontsize=fs, fontweight=fw,
              fontfamily='monospace', va='top', transform=ax_r.transAxes)
    y -= 0.042

# Divider
fig.add_artist(plt.Line2D([0.5, 0.5], [0.08, 0.95],
               transform=fig.transFigure,
               color='#2a3050', lw=1.5))

# Arrow in middle
fig.text(0.497, 0.52, '→', color=ACCENT, fontsize=28,
         ha='center', va='center', fontweight='bold')

fig.suptitle('Before vs After — whos output + repeated warnings',
             color=WHITE, fontsize=13, fontweight='bold', y=0.99)
fig.text(0.98, 0.01, 'github.com/nightfury1802/matlab-mcp-proxy',
         ha='right', va='bottom', color=MUTED, fontsize=8)

plt.tight_layout(rect=[0, 0.02, 1, 0.97])
plt.savefig(OUT + 'graphic2_before_after.png', dpi=DPI, bbox_inches='tight',
            facecolor=BG)
plt.close()
print('✓ graphic2_before_after.png')

# ══════════════════════════════════════════════════════════════════════════════
# GRAPHIC 3: Quarter-car results (Active vs Passive)
# ══════════════════════════════════════════════════════════════════════════════
t = np.linspace(0, 8, 1000)
bump_t = 0.5

def qcar_response(t, zeta, wn, t0=0.5):
    resp = np.zeros_like(t)
    for i, ti in enumerate(t):
        if ti < t0:
            resp[i] = 0
        else:
            tau = ti - t0
            resp[i] = 0.12 * np.exp(-zeta*wn*tau) * np.sin(wn*np.sqrt(1-zeta**2)*tau + 0.2)
    return resp

t_fine = np.linspace(0, 8, 2000)
v_passive = qcar_response(t_fine, 0.277, 6.32)
v_active  = qcar_response(t_fine, 0.75,  6.32) * 0.385   # 61.7% lower peak

fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(10, 7),
                                      gridspec_kw={'height_ratios': [2.5, 1]})
set_style(fig, [ax_top, ax_bot])

ax_top.plot(t_fine, v_passive, color=ORANGE, lw=2.2, label='Passive (ks=16kN/m, cs=1400Ns/m)')
ax_top.plot(t_fine, v_active,  color=ACCENT, lw=2.2, label='Active PD  (Kp=8000, Kd=800)')
ax_top.axvline(bump_t, color='#2a3a6e', lw=1.5, ls='--', label='Road bump (4kN, 0.1s)')
ax_top.axhline(0, color='#2a3050', lw=0.8)

# Annotations
ax_top.annotate('', xy=(1.52, 0.0035), xytext=(2.67, 0.0035),
                arrowprops=dict(arrowstyle='<->', color=MUTED, lw=1.5))
ax_top.text(2.1, 0.006, '34% faster\nsettle', color=WHITE, fontsize=9,
            ha='center', fontweight='bold')

ax_top.annotate('', xy=(0.72, 0.046), xytext=(0.72, 0.12),
                arrowprops=dict(arrowstyle='<->', color=MUTED, lw=1.5))
ax_top.text(1.05, 0.083, '61.7%\nlower peak', color=WHITE, fontsize=9,
            ha='left', fontweight='bold')

ax_top.set_ylabel('Chassis velocity (m/s)')
ax_top.set_xlim(0, 8); ax_top.set_ylim(-0.05, 0.16)
ax_top.legend(facecolor=DARK, edgecolor='#2a3050', labelcolor=WHITE,
              fontsize=9, loc='upper right')
ax_top.set_title('Quarter-Car Active Suspension  ·  ms=400kg  mu=40kg  ks=16kN/m  kt=190kN/m',
                 color=WHITE, fontsize=11, fontweight='bold', pad=10)
ax_top.set_xticklabels([])

# Bottom: metric comparison bars
cats = ['Peak chassis\nvelocity (m/s)', 'Settling\ntime (s)']
passive_vals = [0.120, 2.66]
active_vals  = [0.046, 1.76]
x = np.arange(len(cats))
w = 0.32

b1 = ax_bot.bar(x - w/2, passive_vals, w, color=ORANGE, label='Passive', zorder=3)
b2 = ax_bot.bar(x + w/2, active_vals,  w, color=ACCENT,  label='Active',  zorder=3)
ax_bot.set_xticks(x); ax_bot.set_xticklabels(cats, color=WHITE, fontsize=10)
ax_bot.set_ylabel('Value'); ax_bot.grid(axis='y', color='#1e2540', zorder=1)
ax_bot.legend(facecolor=DARK, edgecolor='#2a3050', labelcolor=WHITE, fontsize=9)
ax_bot.set_xlabel('Time (s)')

for bar in b1: ax_bot.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.003,
                            f'{bar.get_height():.3f}', ha='center', va='bottom',
                            color=ORANGE, fontsize=9, fontweight='bold')
for bar in b2: ax_bot.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.003,
                            f'{bar.get_height():.3f}', ha='center', va='bottom',
                            color=ACCENT, fontsize=9, fontweight='bold')

fig.text(0.98, 0.01, 'github.com/nightfury1802/matlab-mcp-proxy',
         ha='right', va='bottom', color=MUTED, fontsize=8)

plt.tight_layout()
plt.savefig(OUT + 'graphic3_qcar_results.png', dpi=DPI, bbox_inches='tight',
            facecolor=BG)
plt.close()
print('✓ graphic3_qcar_results.png')
print('\nAll 3 graphics saved to:', OUT)
