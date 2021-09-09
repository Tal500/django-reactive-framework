from http import HTTPStatus

from django.test import TestCase, Client

# Create your tests here.

class ExamplePageResponseTest(TestCase):

    def test_get(self):
        """Test the response of the server in example page"""

        c = Client()
        response = c.get(f"/example/")
        self.assertEqual(response.status_code, HTTPStatus.OK)
        
        content = str(response.content)

        # Make sure that John Smith is in the page.
        content.find('John')
        self.assertNotEqual(content.find('John'), -1)
        self.assertNotEqual(content.find('Smith'), -1)

        # Make sure that the 'Increase Age' button is there.
        self.assertNotEqual(content.find('value="Increase Age"'), -1)