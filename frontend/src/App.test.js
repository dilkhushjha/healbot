import { render, screen } from '@testing-library/react';
import App from './App';

test('renders the Healbot dashboard entry screen', () => {
  render(<App />);
  expect(screen.getByText(/HealBot/i)).toBeInTheDocument();
  expect(screen.getByText(/Create your account/i)).toBeInTheDocument();
});
