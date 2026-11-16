import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: ['src/shop/static/shop/js/vendor/**'],
  },
  {
    files: ['src/shop/static/shop/js/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
    },
    rules: js.configs.recommended.rules,
  },
];
