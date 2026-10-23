import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import hooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
export default tseslint.config(
  { ignores: ['.next/**', 'next-env.d.ts', 'coverage/**', 'backend/**', 'Documents/**'] },
  { files: ['app/**/*.{ts,tsx}', 'components/**/*.{ts,tsx}', 'lib/**/*.{ts,tsx}'], rules: {
    'no-restricted-imports': ['error', { patterns: ['**/backend/**', '**/supabase/**', 'papaparse', '@google/genai', 'node:sqlite'] }],
  } },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { languageOptions: { globals: { ...globals.browser, ...globals.node } } },
  { files: ['**/*.{ts,tsx}'], plugins: { 'react-hooks': hooks }, rules: hooks.configs.recommended.rules },
);
