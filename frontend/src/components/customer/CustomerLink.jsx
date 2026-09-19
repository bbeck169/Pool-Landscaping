/**
 * Feb-2026 · Clickable Customer Data — `<CustomerLink>`.
 *
 * Wraps a customer's name in a React Router link to their detail
 * page. Falls back to a plain span when the id is missing (leads
 * without a `customer_id`, referral candidates on the marketing
 * side, historic rows) so the primitive stays safe to sprinkle
 * across every surface that renders customer data.
 *
 * Click stops propagation so anchor-in-clickable-row surfaces
 * don't double-navigate. Typography is inherited from parent —
 * the primitive only adds a hover-underline.
 */
import React from "react";
import { Link } from "react-router-dom";


export const CustomerLink = ({
  customerId,
  name,
  className,
  children,
  ...rest
}) => {
  const label = name ?? children ?? "";
  if (!customerId || !String(customerId).trim()) {
    return (
      <span
        className={className}
        data-testid="customer-name-link"
        data-invalid="true"
        {...rest}
      >
        {label}
      </span>
    );
  }
  return (
    <Link
      to={`/customers/${customerId}`}
      title={typeof label === "string" ? label : undefined}
      className={
        `hover:underline focus:underline ` + (className || "")
      }
      data-testid="customer-name-link"
      onClick={(e) => e.stopPropagation()}
      {...rest}
    >
      {label}
    </Link>
  );
};

export default CustomerLink;
