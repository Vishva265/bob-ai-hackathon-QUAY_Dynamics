import parser from '@typescript-eslint/parser';

export default [{
  files: ['src/**/*.{ts,tsx}', 'e2e/**/*.mjs'],
  languageOptions: {parser, parserOptions: {ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: {jsx: true}}},
  rules: {
    'no-dupe-args': 'error', 'no-dupe-keys': 'error', 'no-unreachable': 'error',
    'no-unsafe-finally': 'error', 'no-debugger': 'error',
    'no-constant-binary-expression': 'error', 'constructor-super': 'error',
    'valid-typeof': 'error', 'no-unexpected-multiline': 'error',
  },
}];
