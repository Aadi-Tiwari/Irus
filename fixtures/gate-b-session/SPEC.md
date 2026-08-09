# Orders service

Three features. Written the way a product spec normally is: it says what the
feature does and leaves the implementation details to whoever builds it.

## 1. Checkout

A customer submits a checkout. We need their email address and the amount they
are paying, in cents. The service creates an order and responds with the new
order's identifier and its status.

## 2. Update profile

A signed-in customer can change their display name and their marketing email
preference (on or off). The service responds with the updated profile.

## 3. Upload a receipt

A customer attaches a receipt image to an existing order. The service stores it
and responds with the stored file's identifier.
