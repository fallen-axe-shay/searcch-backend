# logic for /login

from flask import abort, jsonify, request, make_response, Blueprint, Response
from flask_restful import reqparse, Resource, fields, marshal
import requests
import datetime
import sqlalchemy
import logging

from searcch_backend.api.app import db, app, config_name
from searcch_backend.api.common.auth import (
    verify_api_key, lookup_token, verify_token)
from searcch_backend.models.model import *
from searcch_backend.models.schema import *

LOG = logging.getLogger(__name__)

def verify_strategy(strategy):
    if strategy not in ['github']:
        abort(403, description="missing/incorrect strategy")


def create_new_session(user, sso_token):
    expiry_timestamp = datetime.datetime.now() + \
      datetime.timedelta(minutes=app.config['SESSION_TIMEOUT_IN_MINUTES'])
    new_session = Sessions(
        user=user, sso_token=sso_token, expires_on=expiry_timestamp,
        is_admin=False)
    db.session.add(new_session)
    #
    # Handle race condition caused by the choice not to lock this table; hit
    # lookup_token if error on assumption it is most likely a duplicate
    # session, to check for a race triggered by multi-post login frontend case.
    # But if still a problem, re-raise.
    #
    try:
        db.session.commit()
        db.session.refresh(new_session)
        return (new_session, True)
    except sqlalchemy.exc.IntegrityError as err:
        db.session.rollback()
        login_session = lookup_token(sso_token)
        if login_session:
            return (login_session, False)
        raise
    except:
        abort(500, description="unexpected internal error in session creation")

class LoginAPI(Resource):
    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(name='token',
                                   type=str,
                                   required=True,
                                   default='',
                                   help='missing SSO token from auth provider in post request')
        self.reqparse.add_argument(name='strategy',
                                   type=str,
                                   default='',
                                   required=True,
                                   help='missing auth strategy in post request')

        self.putparse = reqparse.RequestParser()
        self.putparse.add_argument(name='is_admin',
                                   type=bool,
                                   required=True,
                                   help='Set admin mode for this session, if authorized')

    def put(self):
        verify_api_key(request)
        login_session = verify_token(request)

        if not login_session.user.can_admin:
            abort(403, description="unauthorized")

        args = self.putparse.parse_args(strict=True)
        login_session.is_admin = args["is_admin"]
        db.session.commit()

        return Response(status=200)

    def post(self):
        args = self.reqparse.parse_args(strict=True)

        verify_api_key(request)

        strategy = args.get('strategy')
        verify_strategy(strategy)

        sso_token = args.get('token')
        login_session = lookup_token(sso_token)
        if not login_session:
            # get email from Github
            github_user_email_api = 'https://api.github.com/user/emails'
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'Authorization': sso_token
            }
            response = requests.get(github_user_email_api, headers=headers)
            if response.status_code != requests.codes.ok:
                abort(response.status_code, description="invalid SSO token")
            response_json = response.json()[0]
            user_email = response_json["email"]

            # check if User entity with that email exists
            user = db.session.query(User).\
              join(Person, Person.id == User.person_id).\
              filter(Person.email == user_email).\
              first()

            if user:  # create new session
                (login_session, is_new) = create_new_session(user, sso_token)
                # Use the login_session.user object for consistency with the
                # following case, even though it cannot matter here.
                user = login_session.user
                msg = "created new session"
                if not is_new:
                    msg = "existing valid session"
                response = jsonify({
                    "userid": user.id,
                    "person": PersonSchema().dump(user.person),
                    "can_admin": user.can_admin,
                    "is_admin": False,
                    "message": "login successful: %s" % (msg,)
                })
                LOG.debug("login successful: existing user, %s (%r)", msg, login_session)
                response.headers.add('Access-Control-Allow-Origin', '*')
                response.status_code = 200
                return response
            else:  # create new user
                github_user_details_api = 'https://api.github.com/user'
                headers = {
                    'Accept': 'application/vnd.github.v3+json',
                    'Authorization': sso_token
                }
                response = requests.get(github_user_details_api, headers=headers)
                
                if response.status_code != requests.codes.ok:
                    abort(response.status_code, description="invalid SSO token")
                
                user_details_json = response.json()
                user_name = user_details_json["name"] if user_details_json["name"] else user_details_json["login"]

                # create database entities
                #
                # Handle race condition due to not locking this table where
                # user creation can race by not committing the new user until
                # we commit the session add.  Sesssion.sso_token is fully
                # unique; only one session per token.
                #
                # NB: note that is not safe to use the new_user or new_person
                # objects here, because if we have to rollback the session
                # in create_new_session due to duplicate, they are uncommitted.
                # So after a call to create_new_session, only use the returned
                # login_session object.
                #
                new_person = Person(name=user_name, email=user_email)
                new_user = User(person=new_person)
                db.session.add(new_user)

                (login_session, is_new) = create_new_session(new_user, sso_token)
                if not is_new:
                    msg = "existing valid session"
                else:
                    msg = "new session"
                response = jsonify({
                    "userid": login_session.user_id,
                    "person": PersonSchema().dump(login_session.user.person),
                    "can_admin": False,
                    "is_admin": False,
                    "message": "login successful: %s" % (msg,)
                })
                LOG.debug("login successful: new user: %s (%r)", msg, login_session)
                response.headers.add('Access-Control-Allow-Origin', '*')
                response.status_code = 200
                return response
        else:
            LOG.debug("login successful: existing session (%r)",login_session)
            existing_user = login_session.user
            existing_person = existing_user.person
            response = jsonify({
                "userid": login_session.user_id,
                "person": PersonSchema().dump(existing_person),
                "can_admin": existing_user.can_admin,
                "is_admin": login_session.is_admin,
                "message": "login successful: valid session"
            })
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.status_code = 200
            return response
