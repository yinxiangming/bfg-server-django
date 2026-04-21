import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from allauth.account.models import EmailAddress, EmailConfirmation
from bfg.common.models.staff import StaffMember

User = get_user_model()

@pytest.mark.django_db
def test_email_first_onboarding_flow(settings):
    """
    Test the Email-First Onboarding (Resale Marketing Flow).
    
    Flow:
    1. Register with email + store details (provisioning deferred).
    2. Email confirmation is required by default.
    3. User clicks the email verification link (verify email).
    4. Provide the workspace setup parameters to finalizer.
    """
    # 1. Enforce our switches
    settings.EMAIL_VERIFICATION_REQUIRED = True
    settings.ONBOARDING_PROVISION_ON_REGISTER = False

    client = APIClient()

    settings.SITE_ID = 1

    # Create dummy Site for allauth
    from django.contrib.sites.models import Site
    Site.objects.get_or_create(id=1, defaults={'domain': 'example.com', 'name': 'example.com'})

    # Step 1: Register User
    register_payload = {
        "email": "test-resale-flow@example.com",
        "password": "StrongPassword123!",
        "password_confirm": "StrongPassword123!",
        "name": "Jane Resale",
        "store_name": "Jane's Vintage Store"
    }

    res = client.post('/api/v1/auth/register/', register_payload, format='json')
    assert res.status_code == 201, f"Registration should succeed, got {res.status_code}: {res.data}"

    # Verify user exists but is not fully provisioned yet
    user = User.objects.get(email="test-resale-flow@example.com")
    assert not user.is_active, "User should be inactive until email is verified"
    
    email_record = EmailAddress.objects.get(user=user, email=user.email)
    assert not email_record.verified, "Email should not be verified yet"

    # Ensure no workspace or staff created yet (because ONBOARDING_PROVISION_ON_REGISTER is False)
    assert not StaffMember.objects.filter(user=user).exists(), "No staff record should exist yet"

    # Step 2: Extract verification token (mocking the email click)
    confirmation = EmailConfirmation.objects.filter(email_address=email_record).first()
    if not confirmation:
        # In case EmailAddress.send_confirmation creates EmailConfirmationHMAC instead of db record
        from allauth.account.models import EmailConfirmationHMAC
        confirmation = EmailConfirmationHMAC(email_address=email_record)
    
    token = confirmation.key

    # Step 3: Verify Email
    # Our AuthVerifyEmailClient hits verify-email endpoint
    verify_res = client.post('/api/v1/auth/verify-email/', {"key": token}, format='json')
    assert verify_res.status_code == 200, f"Email verification should succeed, got {verify_res.status_code}"

    email_record.refresh_from_db()
    assert email_record.verified, "Email should be verified now"
    
    # After allauth verifies, user should be active
    user.refresh_from_db()
    assert user.is_active, "User should become active after verification"

    # Step 4: Provisioning Workspace (Frontend calls /api/v1/auth/token/ to login, then sets up workspace)
    # We test the end goal: can the user authenticate and would they have access?
    # In the real system, completing the wizard would call the workspace creation API.
    # For now, we just ensure they can get a token now that they are active.
    token_res = client.post('/api/v1/auth/token/', {
        "email": "test-resale-flow@example.com",
        "password": "StrongPassword123!"
    }, format='json')
    
    assert token_res.status_code == 200, "Should be able to login and get tokens after verification"
    assert 'access' in token_res.data
