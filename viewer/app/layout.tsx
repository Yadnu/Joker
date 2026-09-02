import type { Metadata } from 'next'
import { Barlow_Condensed, JetBrains_Mono, Inter } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'

const barlowCondensed = Barlow_Condensed({
  weight: ['400', '500', '600', '700'],
  style: ['normal', 'italic'],
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Jokebox Viewer',
  description: 'Archive viewer — trace every joke from first prompt to final punchline.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${barlowCondensed.variable} ${jetbrainsMono.variable} ${inter.variable}`}
    >
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
